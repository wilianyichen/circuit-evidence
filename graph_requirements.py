"""Compare caller-declared numerical thresholds with explicit-graph observations."""
import math
from pathlib import Path

ORIGINS = {'original', 'later_user', 'assumption', 'extra_test'}


def summarize(rows):
    """Aggregate declared-check outcomes only; never treat this as task acceptance."""
    if not isinstance(rows,list) or not rows:raise ValueError('nonempty check results required')
    allowed={'pass','fail','indeterminate','nominal_pass','nominal_fail',
             'sampled_pass','sampled_fail','sampled_indeterminate','sampled_nominal_pass','sampled_nominal_fail'}
    decisions=[row.get('decision') if isinstance(row,dict) else None for row in rows]
    if any(not isinstance(x,str) or x not in allowed for x in decisions):raise ValueError('unknown check decision')
    counts={'passed':sum(x.endswith('pass') for x in decisions),
            'failed':sum(x.endswith('fail') for x in decisions),
            'indeterminate':sum('indeterminate' in x for x in decisions)}
    status=('some_declared_checks_failed' if counts['failed'] else
            'some_declared_checks_indeterminate' if counts['indeterminate'] else
            'all_declared_checks_passed')
    return {'status':status,'total':len(rows),**counts,
            'scope':'caller-declared finite checks only; not task or hardware acceptance'}


def finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def dimension(measurement):
    return 'V' if measurement['kind'] == 'voltage' else 'A'


def validate(req, checks):
    if not isinstance(checks, list) or not 1 <= len(checks) <= 30:
        raise ValueError('checks must contain 1 to 30 entries')
    measurements = req['measurements']; seen = set()
    common = {'id', 'origin', 'description', 'kind', 'comparison', 'threshold', 'uncertainty'}
    for row in checks:
        if not isinstance(row, dict) or not common <= set(row):
            raise ValueError('check is missing required fields')
        if not isinstance(row['id'], str) or not row['id'].strip() or row['id'] in seen:
            raise ValueError('check ids must be unique nonempty strings')
        seen.add(row['id'])
        if not isinstance(row['origin'], str) or row['origin'] not in ORIGINS or not isinstance(row['description'], str) or not row['description'].strip():
            raise ValueError('check needs an origin and description')
        if row['comparison'] not in ('>=', '<=', '>', '<') or not finite(row['threshold']) or (row['uncertainty'] is not None and (not finite(row['uncertainty']) or row['uncertainty'] < 0)):
            raise ValueError('invalid comparison, threshold or uncertainty')
        kind = row['kind']
        if kind == 'window_linear_combination':
            expected = common | {'terms', 'start_s', 'end_s'}; indices = []
            terms = row.get('terms')
            nodes = {n.lower() for e in req['elements'] for n in e['nodes']} | {'0'}
            if (not finite(row.get('start_s')) or not finite(row.get('end_s')) or
                not 0 <= row['start_s'] < row['end_s'] <= req['analysis']['stop_s'] or
                row['comparison'] not in ('<', '<=') or row['threshold'] < 0 or
                not isinstance(terms, list) or not 2 <= len(terms) <= 8):
                raise ValueError('invalid linear combination window, bound or terms')
            pairs = set()
            for term in terms:
                if (not isinstance(term, dict) or set(term) != {'positive', 'negative', 'coefficient'} or
                    any(not isinstance(term[k], str) or term[k].lower() not in nodes for k in ('positive', 'negative')) or
                    term['positive'].lower() == term['negative'].lower() or
                    not finite(term['coefficient']) or not 0 < abs(term['coefficient']) <= 1e12):
                    raise ValueError('invalid linear combination voltage term')
                pair = tuple(sorted((term['positive'].lower(), term['negative'].lower())))
                if pair in pairs: raise ValueError('duplicate linear combination voltage term')
                pairs.add(pair)
        elif kind == 'window_extremum':
            expected = common | {'index', 'scale', 'start_s', 'end_s', 'statistic'}
            indices = [row.get('index')]
            if (not finite(row.get('start_s')) or not finite(row.get('end_s')) or
                not 0 <= row['start_s'] < row['end_s'] <= req['analysis']['stop_s'] or
                row.get('statistic') not in ('min', 'max', 'max_abs', 'peak_to_peak')):
                raise ValueError('invalid window or statistic')
        elif kind == 'measurement':
            expected = common | {'index', 'scale'}
            indices = [row.get('index')]
        elif kind in ('ratio', 'ratio_db'):
            expected = common | {'numerator', 'denominator', 'scale', 'minimum_denominator_abs'}
            indices = [row.get('numerator'), row.get('denominator')]
            if not finite(row.get('minimum_denominator_abs')) or row['minimum_denominator_abs'] <= 0:
                raise ValueError('ratio needs a positive minimum_denominator_abs')
        elif kind == 'max_resistor':
            expected = common; indices = []
        else:
            raise ValueError('unsupported check kind')
        if set(row) != expected:
            raise ValueError('unexpected or missing fields in ' + row['id'])
        if any(type(i) is not int or not 0 <= i < len(measurements) for i in indices):
            raise ValueError('measurement index outside request')
        if kind not in ('max_resistor', 'window_linear_combination') and (not finite(row['scale']) or row['scale'] not in (-1, 1)):
            raise ValueError('scale must be +1 or -1')
        if len(indices) == 2:
            a, b = [measurements[i] for i in indices]
            if a['at_s'] != b['at_s']:
                raise ValueError('ratio measurements must have the same requested time')
            if kind == 'ratio_db' and dimension(a) != dimension(b):
                raise ValueError('ratio_db requires matching voltage or current dimensions')


def evaluate(req, result, checks):
    validate(req, checks)
    if result.get('status') != 'native_simulation_completed_requires_review':
        raise ValueError('native simulation result required')
    observations = result.get('observations')
    if not isinstance(observations, list) or len(observations) != len(req['measurements']):
        raise ValueError('observations do not match request')
    for expected, observed in zip(req['measurements'], observations):
        if not isinstance(observed, dict) or set(observed) != set(expected) | {'value'} or any(observed[k] != v for k, v in expected.items()) or not finite(observed['value']):
            raise ValueError('observation identity or value does not match request')
    evaluated = []
    window_cache = {}
    for row in checks:
        kind = row['kind']; value = None; reason = None; evidence = []
        if kind == 'max_resistor':
            resistors = [e for e in req['elements'] if e['kind'] == 'R']
            if resistors:
                value = max(e['value'] for e in resistors); unit = 'ohm'
                evidence = [{'ref': e['ref'], 'nominal_ohm': e['value']} for e in resistors]
            else:
                unit = 'ohm'; reason = 'no resistors in declared graph'
        elif kind == 'window_linear_combination':
            value, details = window_linear_combination(result, row, window_cache)
            unit = 'V'; evidence = [details]
        elif kind == 'window_extremum':
            i = row['index']; m = req['measurements'][i]
            value, details = window_extremum(result, m, row, window_cache)
            unit = dimension(m); evidence = [details]
        elif kind == 'measurement':
            i = row['index']; evidence = [observations[i]]
            value = row['scale'] * observations[i]['value']; unit = dimension(req['measurements'][i])
        else:
            a, b = row['numerator'], row['denominator']
            numerator, denominator = observations[a]['value'], observations[b]['value']
            evidence = [observations[a], observations[b]]
            dim_a = dimension(req['measurements'][a]); dim_b = dimension(req['measurements'][b])
            unit = 'dB' if kind == 'ratio_db' else '1' if dim_a == dim_b else dim_a + '/' + dim_b
            if abs(denominator) < row['minimum_denominator_abs']:
                reason = 'denominator below caller-declared minimum'
            elif kind == 'ratio_db' and numerator == 0:
                reason = 'zero numerator has no finite dB value'
            elif kind == 'ratio_db':
                value = 20 * (math.log10(abs(numerator)) - math.log10(abs(denominator)))
            else:
                value = row['scale'] * numerator / denominator
        if value is not None and not finite(value):
            value = None; reason = 'nonfinite derived value'
        if value is None:
            decision = 'indeterminate'
        elif row['uncertainty'] is None:
            compare = {'>=': lambda a,b:a>=b, '>':lambda a,b:a>b, '<=':lambda a,b:a<=b, '<':lambda a,b:a<b}[row['comparison']]
            decision = 'nominal_pass' if compare(value, row['threshold']) else 'nominal_fail'
        elif row['comparison'] == '>=':
            decision = 'pass' if value - row['uncertainty'] >= row['threshold'] else 'fail' if value + row['uncertainty'] < row['threshold'] else 'indeterminate'
        elif row['comparison'] == '>':
            decision = 'pass' if value - row['uncertainty'] > row['threshold'] else 'fail' if value + row['uncertainty'] <= row['threshold'] else 'indeterminate'
        elif row['comparison'] == '<=':
            decision = 'pass' if value + row['uncertainty'] <= row['threshold'] else 'fail' if value - row['uncertainty'] > row['threshold'] else 'indeterminate'
        else:
            decision = 'pass' if value + row['uncertainty'] < row['threshold'] else 'fail' if value - row['uncertainty'] >= row['threshold'] else 'indeterminate'
        if kind in ('window_extremum', 'window_linear_combination'):
            decision = 'sampled_' + decision
        evaluated.append({'declaration': row, 'value': value, 'unit': unit, 'decision': decision,
                          'reason': reason, 'evidence': evidence})
    return evaluated


def window_linear_combination(result, row, cache):
    """Check synchronized saved voltages, not unsampled or physical behavior."""
    import numpy as np
    from spicelib import RawRead
    from raw_trace_contract import check, file_sha256

    path = Path(result['raw_path']).resolve(strict=True)
    expected_hash = result['raw_sha256'].lower()
    if not path.is_relative_to(Path(result['run_dir']).resolve(strict=True)) or path.suffix.lower() != '.raw':
        raise ValueError('RAW must be inside the run directory')
    nodes = sorted({term[k].lower() for term in row['terms'] for k in ('positive', 'negative')} - {'0'})
    required = ['time'] + ['V('+n+')' for n in nodes]
    key = (str(path), expected_hash, tuple(required))
    if key not in cache:
        contract = check(path, required)
        if contract['raw_sha256'] != expected_hash or contract['status'] != 'complete':
            raise ValueError('RAW hash mismatch or required traces missing or ambiguous')
        raw = RawRead(str(path), traces_to_read=list(contract['resolved'].values()))
        props = raw.get_raw_property()
        if props.get('Plotname') != 'Transient Analysis' or 'stepped' in props.get('Flags', '').lower():
            raise ValueError('only unstepped transient RAW is supported')
        t = np.asarray(raw.get_axis(), dtype=float)
        traces = {name: np.asarray(raw.get_trace(contract['resolved'][name]).get_wave(), dtype=float)
                  for name in required if name != 'time'}
        if (len(t) < 2 or not np.isfinite(t).all() or np.any(np.diff(t) <= 0) or
            any(y.shape != t.shape or not np.isfinite(y).all() for y in traces.values())):
            raise ValueError('invalid saved transient axis or trace')
        if file_sha256(path) != expected_hash: raise ValueError('RAW changed during read')
        cache[key] = (t, traces)
    t, traces = cache[key]
    start, end = row['start_s'], row['end_s']
    if not t[0] <= start < end <= t[-1]: raise ValueError('window outside saved RAW')
    with np.errstate(over='ignore', invalid='ignore'):
        y = np.zeros_like(t)
        for term in row['terms']:
            def voltage(node):
                return 0.0 if node.lower() == '0' else traces['V('+node.lower()+')']
            y += term['coefficient'] * (voltage(term['positive']) - voltage(term['negative']))
    if not np.isfinite(y).all(): raise ValueError('nonfinite linear combination')
    left = np.searchsorted(t, start, side='right'); right = np.searchsorted(t, end, side='left')
    tw = np.concatenate(([start], t[left:right], [end]))
    yw = np.interp(tw, t, y); ix = int(np.argmax(np.abs(yw)))
    lo = max(0, int(np.searchsorted(t, start))-1); hi = min(len(t), int(np.searchsorted(t, end, side='right'))+1)
    return float(abs(yw[ix])), {'raw_path': str(path), 'raw_sha256': expected_hash,
        'trace_names': required[1:], 'window_s': [start, end], 'terms': row['terms'],
        'extremum_time_s': float(tw[ix]), 'signed_value_at_extremum_v': float(yw[ix]),
        'window_points_including_interpolated_endpoints': len(tw),
        'largest_bracketing_saved_gap_s': float(np.max(np.diff(t[lo:hi]))),
        'scope': 'synchronized saved samples and linearly interpolated endpoints only; peaks between saved points may be missed'}


def window_extremum(result, measurement, row, cache):
    """Evaluate saved points and linearly interpolated endpoints, not a continuous guarantee."""
    import numpy as np
    from spicelib import RawRead
    from raw_trace_contract import check, file_sha256

    path = Path(result['raw_path']).resolve(strict=True)
    expected_hash = result['raw_sha256'].lower()
    if not path.is_relative_to(Path(result['run_dir']).resolve(strict=True)) or path.suffix.lower() != '.raw':
        raise ValueError('RAW must be inside the run directory')
    if measurement['kind'] == 'voltage':
        refs = [('V('+measurement[k]+')' if measurement[k] != '0' else None) for k in ('positive', 'negative')]
    else:
        refs = ['I('+measurement['ref']+')']
    required = ['time'] + list(dict.fromkeys(x for x in refs if x is not None))
    key = (str(path), expected_hash, tuple(required))
    if key not in cache:
        contract = check(path, required)
        if contract['raw_sha256'] != expected_hash or contract['status'] != 'complete':
            raise ValueError('RAW hash mismatch or required traces missing or ambiguous')
        raw = RawRead(str(path), traces_to_read=list(contract['resolved'].values()))
        props = raw.get_raw_property()
        if props.get('Plotname') != 'Transient Analysis' or 'stepped' in props.get('Flags', '').lower():
            raise ValueError('only unstepped transient RAW is supported')
        t = np.asarray(raw.get_axis(), dtype=float)
        traces = {name: np.asarray(raw.get_trace(contract['resolved'][name]).get_wave(), dtype=float)
                  for name in required if name != 'time'}
        if (len(t) < 2 or not np.isfinite(t).all() or np.any(np.diff(t) <= 0) or
            any(y.shape != t.shape or not np.isfinite(y).all() for y in traces.values())):
            raise ValueError('invalid saved transient axis or trace')
        if file_sha256(path) != expected_hash:
            raise ValueError('RAW changed during read')
        cache[key] = (t, traces)
    t, traces = cache[key]
    start, end = row['start_s'], row['end_s']
    if not t[0] <= start < end <= t[-1]:
        raise ValueError('window outside saved RAW')
    if len(refs) == 1:
        y = traces[refs[0]]
    else:
        y = (traces[refs[0]] if refs[0] else np.zeros_like(t)) - (traces[refs[1]] if refs[1] else np.zeros_like(t))
    left = np.searchsorted(t, start, side='right'); right = np.searchsorted(t, end, side='left')
    tw = np.concatenate(([start], t[left:right], [end]))
    yw = row['scale'] * np.interp(tw, t, y)
    statistic = row['statistic']
    if statistic not in ('min','max','max_abs','peak_to_peak'):
        raise ValueError('unsupported window statistic')
    if statistic == 'peak_to_peak':
        i_min, i_max = int(np.argmin(yw)), int(np.argmax(yw))
        value = float(yw[i_max] - yw[i_min])
        extrema = {'minimum_value': float(yw[i_min]), 'minimum_time_s': float(tw[i_min]),
                   'maximum_value': float(yw[i_max]), 'maximum_time_s': float(tw[i_max])}
    else:
        ix = int(np.argmin(yw) if statistic == 'min' else np.argmax(np.abs(yw)) if statistic == 'max_abs' else np.argmax(yw))
        value = float(abs(yw[ix]) if statistic == 'max_abs' else yw[ix])
        extrema = {'extremum_time_s': float(tw[ix])}
    lo = max(0, int(np.searchsorted(t, start))-1); hi = min(len(t), int(np.searchsorted(t, end, side='right'))+1)
    return value, {'raw_path': str(path), 'raw_sha256': expected_hash, 'trace_names': refs,
                   'window_s': [start, end], 'statistic': statistic,
                   **extrema, 'window_points_including_interpolated_endpoints': len(tw),
                   'largest_bracketing_saved_gap_s': float(np.max(np.diff(t[lo:hi]))),
                   'scope': 'saved points and linearly interpolated endpoints only; transient peaks between saved points may be missed'}
