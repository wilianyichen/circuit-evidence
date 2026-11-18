"""Run a declared transient circuit and retain requirement-to-waveform evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np
from spicelib import RawRead

from graph_requirements import evaluate, finite, summarize, validate
from raw_trace_contract import check, file_sha256
from requirement_trace import check_source_grounding, check_trace

ROOT = Path(__file__).resolve().parent
EXAMPLES = ('motor-drive', 'resistor-blackbox')
VARIANTS = ('positive', 'negative')
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}')


def number(value):
    if not finite(value):
        raise ValueError('expected finite number')
    return format(value, '.16g')


def deck(request):
    lines = ['* Circuit Evidence transient test']
    nodes, refs = set(), set()
    elements = request['elements']
    if not 1 <= len(elements) <= 100:
        raise ValueError('expected 1 to 100 elements')
    for element in elements:
        kind, ref, pins = (element[key] for key in ('kind', 'ref', 'nodes'))
        if kind not in ('R', 'V', 'I', 'E') or not IDENTIFIER.fullmatch(ref) or not ref.upper().startswith(kind):
            raise ValueError('unsupported element or invalid designator')
        if ref.casefold() in refs:
            raise ValueError('duplicate designator')
        refs.add(ref.casefold())
        if len(pins) != (4 if kind == 'E' else 2) or any(n != '0' and not IDENTIFIER.fullmatch(n) for n in pins):
            raise ValueError('invalid ordered terminals')
        nodes.update(n.lower() for n in pins)
        if kind == 'R':
            value = number(element['value'])
            if element['value'] <= 0:
                raise ValueError('resistance must be positive')
        elif kind == 'E':
            value = number(element['gain'])
        else:
            source = element['source']
            if kind == 'I' and set(source) == {'dc_a'}:
                value = 'DC ' + number(source['dc_a'])
            elif kind == 'V' and set(source) == {'dc_v'}:
                value = number(source['dc_v'])
            elif kind == 'V' and set(source) == {'pwl'}:
                pairs = source['pwl']
                if not 2 <= len(pairs) <= 100 or any(len(pair) != 2 for pair in pairs):
                    raise ValueError('expected 2 to 100 PWL pairs')
                flat = ' '.join(number(v) for pair in pairs for v in pair)
                times = [pair[0] for pair in pairs]
                if times[0] < 0 or any(a >= b for a, b in zip(times, times[1:])):
                    raise ValueError('PWL times must increase from a nonnegative time')
                value = 'PWL(' + flat + ')'
            else:
                raise ValueError('unsupported source')
        lines.append(' '.join([ref, *pins, value]))
    if '0' not in nodes or len(nodes) < 2:
        raise ValueError('circuit needs ground and at least one other node')
    analysis = request['analysis']
    stop, step = analysis['stop_s'], analysis['max_step_s']
    if not finite(stop) or not finite(step) or not 0 < step <= stop or stop / step > 100_000:
        raise ValueError('invalid transient duration or maximum step')
    for m in request['measurements']:
        if (set(m) != {'kind', 'positive', 'negative', 'at_s'} or m['kind'] != 'voltage'
                or any(m[n] not in nodes for n in ('positive', 'negative'))
                or not finite(m['at_s']) or not 0 <= m['at_s'] <= stop):
            raise ValueError('expected a voltage measurement on declared lowercase nodes and time')
    lines += ['.options plotwinsize=0 reltol=1e-6', f'.tran 0 {number(stop)} 0 {number(step)}',
              '.save ' + ' '.join(f'V({n})' for n in sorted(nodes - {'0'})), '.end']
    return '\n'.join(lines) + '\n', sorted(nodes - {'0'})


def observations(path, nodes, measurements, raw_hash):
    names = ['time', *(f'V({node})' for node in nodes)]
    contract = check(path, names)
    if contract['status'] != 'complete' or contract['raw_sha256'] != raw_hash:
        raise ValueError('RAW trace set or hash differs')
    raw = RawRead(str(path), traces_to_read=list(contract['resolved'].values()))
    props = raw.get_raw_property()
    if props.get('Plotname') != 'Transient Analysis' or 'stepped' in props.get('Flags', '').lower():
        raise ValueError('expected an unstepped transient RAW')
    t = np.asarray(raw.get_axis(), dtype=float)
    if len(t) < 2 or not np.isfinite(t).all() or not np.all(np.diff(t) > 0):
        raise ValueError('invalid saved time axis')
    volts = {'0': np.zeros_like(t)}
    for node in nodes:
        v = np.asarray(raw.get_trace(contract['resolved'][f'V({node})']).get_wave(), dtype=float)
        if v.shape != t.shape or not np.isfinite(v).all():
            raise ValueError('invalid voltage trace')
        volts[node] = v
    if file_sha256(path) != raw_hash:
        raise ValueError('RAW changed during read')
    rows = []
    for m in measurements:
        at = m['at_s']
        if not t[0] <= at <= t[-1]:
            raise ValueError('measurement time outside saved waveform')
        delta = volts[m['positive']] - volts[m['negative']]
        rows.append({**m, 'value': float(np.interp(at, t, delta))})
    return rows, len(t)


def link_checks(requirements, checks, results, ambiguous):
    rows = []
    for row in requirements:
        linked = []
        for binding in row['bindings']:
            path = binding['path']
            if len(path) != 2 or path[0] != 'checks' or type(path[1]) is not int:
                raise ValueError('bind to a complete checks entry')
            index = path[1]
            if json.dumps(binding['expected'], sort_keys=True, allow_nan=False) != json.dumps(
                    checks[index], sort_keys=True, allow_nan=False):
                raise ValueError('bound check declaration differs in value or type')
            result = results[index]
            if result['declaration'] != checks[index]:
                raise ValueError('result declaration changed')
            linked.append({'id': checks[index]['id'], 'decision': result['decision']})
        if row['id'] in ambiguous:
            status = 'ambiguous_quote_requires_review'
        elif not linked:
            status = 'unresolved'
        elif any(x['decision'].endswith('fail') for x in linked):
            status = 'linked_check_failed'
        elif all(x['decision'].endswith('pass') for x in linked):
            status = 'linked_checks_passed_semantics_unverified'
        else:
            status = 'linked_check_indeterminate'
        rows.append({'id': row['id'], 'text': row['quote'], 'status': status, 'checks': linked})
    return rows


def run(case, source_text, variant, executable, output, *, compare_expected=False):
    if variant not in VARIANTS:
        raise ValueError('unknown variant')
    request = {key: case[key] for key in ('analysis', 'measurements')}
    request['elements'] = case['variants'][variant]['elements']
    checks = case['checks']
    netlist, nodes = deck(request)
    validate(request, checks)
    if any(c['kind'] not in ('measurement', 'window_extremum', 'window_linear_combination') for c in checks):
        raise ValueError('unsupported check in this release')
    task = {'source_text': source_text, 'requirements': case['requirements']}
    trace = check_trace(task, {'spec': {'checks': checks}})
    link_checks(task['requirements'], checks, [{'declaration': c, 'decision': 'indeterminate'} for c in checks], trace['ambiguous_quote_ids'])
    snapshot = source_text.encode('utf-8')
    expected_source = case['source']['sha256']
    if hashlib.sha256(snapshot).hexdigest() != expected_source:
        raise ValueError('source SHA256 mismatch')
    executable = executable.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=variant + '-', dir=output.resolve()))
    source = run_dir / 'requirements.txt'
    source.write_bytes(snapshot)
    grounding, _ = check_source_grounding(task, {
        'source_path': str(source), 'source_sha256': expected_source,
        'start_text': None, 'end_text': None}, run_dir)
    contract = run_dir / 'contract.json'
    contract.write_text(json.dumps(case, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    deck_path = run_dir / 'circuit.cir'
    deck_path.write_bytes(netlist.encode('ascii'))
    deck_hash = file_sha256(deck_path)
    with (run_dir / 'simulator-process.txt').open('wb') as log:
        subprocess.run([str(executable), '-b', deck_path.name], cwd=run_dir,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    raw_path = run_dir / 'circuit.raw'
    raw_hash = file_sha256(raw_path)
    samples, points = observations(raw_path, nodes, request['measurements'], raw_hash)
    results = evaluate(request, {
        'status': 'native_simulation_completed_requires_review', 'observations': samples,
        'run_dir': str(run_dir), 'raw_path': str(raw_path), 'raw_sha256': raw_hash}, checks)
    if (file_sha256(deck_path) != deck_hash or file_sha256(source) != expected_source
            or file_sha256(raw_path) != raw_hash):
        raise ValueError('evidence changed during run')
    summary = summarize(results)
    failed = [r['declaration']['id'] for r in results if r['decision'].endswith('fail')]
    report_path = run_dir / 'evidence.json'
    simulator_log = run_dir / 'circuit.log'
    evidence = {
        'evidence_file': str(report_path), 'variant': variant,
        'source': {**case['source'], 'grounding': grounding}, 'trace': trace,
        'requirements': link_checks(task['requirements'], checks, results, trace['ambiguous_quote_ids']),
        'checks': results, 'summary': summary, 'failed_check_ids': failed,
        'measurements': samples, 'saved_points': points, 'simulator': 'LTspice batch',
        'files': {f.name: file_sha256(f) for f in (source, contract, deck_path, raw_path, simulator_log)},
        'limits': ['Caller owns requirement meaning and coverage.',
                   'Checks use a finite set of simulated points. No physical acceptance.',
                   'Simulation uses the generated netlist directly. No schematic export check.'],
    }
    if compare_expected:
        evidence['expected_failed_ids'] = case['variants'][variant]['expected_failed']
        evidence['regression_passed'] = (
            not summary['indeterminate'] and sorted(failed) == sorted(evidence['expected_failed_ids']))
    report_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return evidence


def run_example(case_id, variant, executable, output):
    if case_id not in EXAMPLES:
        raise ValueError('unknown example')
    folder = ROOT / 'examples' / case_id
    case = json.loads((folder / 'case.json').read_text(encoding='utf-8'))
    source = (folder / 'requirements.txt').read_bytes().decode('utf-8')
    return run(case, source, variant, executable, output / case_id, compare_expected=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ltspice', default=os.environ.get('CIRCUIT_EVIDENCE_LTSPICE'), type=Path, required=not os.environ.get('CIRCUIT_EVIDENCE_LTSPICE'))
    parser.add_argument('--output', type=Path, default=ROOT / 'runs')
    parser.add_argument('--case', choices=EXAMPLES)
    parser.add_argument('--variant', choices=VARIANTS)
    args = parser.parse_args()
    summaries = []
    for case_id in [args.case] if args.case else EXAMPLES:
        for variant in [args.variant] if args.variant else VARIANTS:
            result = run_example(case_id, variant, args.ltspice, args.output)
            summaries.append({key: result[key] for key in (
                'variant', 'summary', 'failed_check_ids', 'regression_passed', 'evidence_file')})
    print(json.dumps(summaries, indent=2))
    return 0 if all(row['regression_passed'] for row in summaries) else 1


if __name__ == '__main__':
    raise SystemExit(main())
