"""Check declared source quotations and their bindings to a bounded solver spec.

This is a provenance and consistency check, not semantic extraction or proof that
the agent listed every requirement, interpreted it correctly, or selected a
sufficient test. Unresolved requirements must not be presented as passes.
"""

import math
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[]
    def handle_data(self,data):
        self.parts.append(data)


def check_source_grounding(task, grounding, root):
    """Match caller text against a hashed local text/HTML selection, not its meaning."""
    required={'source_path','source_sha256','start_text','end_text'}
    if not isinstance(grounding,dict) or set(grounding)!=required:
        raise ValueError('grounding requires source_path, source_sha256, start_text and end_text')
    if not isinstance(grounding['source_path'],str) or not isinstance(grounding['source_sha256'],str):
        raise ValueError('invalid source path or hash')
    path=Path(grounding['source_path']).resolve(strict=True);root=Path(root).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in ('.txt','.md','.html','.htm'):
        raise ValueError('source must be a text or HTML file inside the project')
    if path.stat().st_size>10_000_000:raise ValueError('source exceeds 10 MB')
    raw=path.read_bytes();actual=hashlib.sha256(raw).hexdigest()
    if actual!=grounding['source_sha256'].lower():raise ValueError('source SHA256 mismatch')
    text=raw.decode('utf-8')
    if path.suffix.lower() in ('.html','.htm'):
        parser=_HtmlText();parser.feed(text);parser.close();text=' '.join(parser.parts)
    text=' '.join(text.split());start=grounding['start_text'];end=grounding['end_text']
    if start is None and end is None:
        selected=text;selection='entire_extracted_text'
    else:
        if not isinstance(start,str) or not start or not isinstance(end,str) or not end:
            raise ValueError('section boundaries must both be nonempty strings or both null')
        if text.count(start)!=1 or text.count(end)!=1:raise ValueError('section boundaries must be unique')
        left=text.index(start);right=text.index(end)
        if right<=left:raise ValueError('section end must follow section start')
        selected=text[left:right].strip();selection='caller_selected_section'
    if not isinstance(task,dict) or not isinstance(task.get('source_text'),str):raise ValueError('task source_text is required')
    if ' '.join(task['source_text'].split())!=selected:raise ValueError('task source_text differs from selected source')
    return {'status':'selected_text_matches_source_requires_scope_review','source_path':str(path),
      'source_sha256':actual,'selection':selection,'start_text':start,'end_text':end,
      'selected_characters':len(selected),
      'limits':['source file authenticity is not established by its hash',
        'caller-selected section boundaries may omit task requirements',
        'HTMLParser extracts data text, not a full rendered page, images or equations',
        'matching text does not verify interpretation or requirement completeness']},raw


def check_grounding_snapshot(record,folder):
    """Check the retained evidence; historical records may have no grounding."""
    grounding=record.get('source_grounding')
    if grounding is None:return
    if not isinstance(grounding,dict):raise ValueError('invalid source grounding record')
    if grounding.get('status')=='not_provided':return
    if grounding.get('status')!='selected_text_matches_source_requires_scope_review' or grounding.get('source_unchanged_after_run') is not True:
        raise ValueError('source grounding is not verified')
    expected=(Path(folder)/'grounded-source.bin').resolve(strict=True)
    if Path(grounding['snapshot_path']).resolve(strict=True)!=expected:
        raise ValueError('source snapshot path changed')
    if hashlib.sha256(expected.read_bytes()).hexdigest()!=grounding['source_sha256']:
        raise ValueError('source snapshot changed')


def _value_at(spec, path):
    current = spec
    if not isinstance(path, list) or not path:
        raise ValueError('binding path must be a nonempty list')
    for part in path:
        if isinstance(current, dict) and isinstance(part, str) and part in current:
            current = current[part]
        elif isinstance(current, list) and type(part) is int and 0 <= part < len(current):
            current = current[part]
        else:
            raise ValueError('binding path does not exist: ' + repr(path))
    return current


def _same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(a) and math.isfinite(b) and a == b
    return type(a) is type(b) and a == b


_QUANTITY = re.compile(r'(?<![A-Za-z0-9_.])([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([pnumkKMGµμ]?)(Hz|hz|HZ|Ω|Ω|ohms|Ohms|OHMS|ohm|Ohm|OHM)(?![A-Za-z])')
_SHARED_UNIT_HZ_RANGE = re.compile(r'(?<![A-Za-z0-9_.+\-])(\d+(?:\.\d*)?|\.\d+)\s*[-–—~]\s*(\d+(?:\.\d*)?|\.\d+)\s*([pnumkKMGµμ]?)(Hz|hz|HZ)(?![A-Za-z])')
_PREFIX = {'': 1, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6,
           'm': 1e-3, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9}


def _quantity_check(quote, binding, *, shared_unit_hz_ranges=False):
    """Advisory only: a literal's unit cannot establish its meaning or role."""
    path = binding['path']
    field = next((part for part in reversed(path) if isinstance(part, str)), '')
    dimension = 'hz' if field.endswith('_hz') else 'ohm' if field.endswith('_ohm') else None
    if dimension is None or any(c in quote for c in '/^*×') or re.search(r'\d,\d', quote):
        return None
    ranges=list(_SHARED_UNIT_HZ_RANGE.finditer(quote)) if dimension=='hz' and shared_unit_hz_ranges else []
    if ranges:
        if len(ranges)!=1 or field not in ('start_hz','end_hz'):
            return None
        m=ranges[0]
        if _QUANTITY.search(quote[:m.start()]+quote[m.end():]):return None
        expected=binding['expected']
        if type(expected) not in (int,float) or not math.isfinite(expected):return None
        source=float(m.group(1) if field=='start_hz' else m.group(2))*_PREFIX[m.group(3)]
        return {'path':path,'literal':m.group(0),'source_value_si':source,'spec_value_si':expected,
                'unit':'hz','matches':math.isclose(source,expected,rel_tol=1e-9,abs_tol=1e-12)}
    values = []
    for m in _QUANTITY.finditer(quote):
        unit = 'hz' if m.group(3).lower() == 'hz' else 'ohm'
        if unit == dimension:
            value = float(m.group(1)) * _PREFIX[m.group(2)]
            if not math.isfinite(value):
                return None
            values.append((value, m.group(0)))
    expected = binding['expected']
    if len(values) != 1 or type(expected) not in (int, float) or not math.isfinite(expected):
        return None
    value, literal = values[0]
    return {'path': path, 'literal': literal, 'source_value_si': value, 'spec_value_si': expected,
            'unit': dimension, 'matches': math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12)}


def check_trace(task, request, *, quantity_diagnostics=True):
    if not isinstance(task, dict) or set(task) not in ({'source_text', 'requirements'},
                                                        {'source_text','requirements','quantity_range_mode'}):
        raise ValueError('task requires only source_text and requirements')
    if 'quantity_range_mode' in task and task['quantity_range_mode']!='shared_unit_hz_v1':
        raise ValueError('unsupported quantity range mode')
    source = task['source_text']
    rows = task['requirements']
    if not isinstance(source, str) or not source.strip() or not isinstance(rows, list) or not rows:
        raise ValueError('source_text and a nonempty requirements list are required')
    if not isinstance(request, dict) or not isinstance(request.get('spec'), dict):
        raise ValueError('structured request.spec is required')
    seen = set()
    unresolved = []
    derived = []
    quoted = [False] * len(source)
    ambiguous = []
    quantity_checks = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'quote', 'status', 'bindings'}:
            raise ValueError('each requirement requires id, quote, status and bindings')
        ident, quote = row['id'], row['quote']
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            raise ValueError('requirement ids must be unique nonempty strings')
        seen.add(ident)
        if not isinstance(quote, str) or not quote.strip() or quote not in source:
            raise ValueError('requirement quote must occur verbatim in source_text: ' + ident)
        start = source.find(quote)
        if source.find(quote, start + 1) != -1:
            ambiguous.append(ident)
        else:
            quoted[start:start + len(quote)] = [True] * len(quote)
        bindings = row['bindings']
        if not isinstance(bindings, list):
            raise ValueError('bindings must be a list')
        if row['status'] == 'unresolved':
            if bindings:
                raise ValueError('unresolved requirement must not claim bindings')
            unresolved.append(ident)
            continue
        if row['status'] == 'derive_rc_frequency_response':
            if bindings:
                raise ValueError('derived response requirement must not claim spec bindings')
            if request['spec'].get('topology') not in ('rc_lowpass','rc_highpass'):
                raise ValueError('RC frequency response requires a supported passive RC topology')
            derived.append(ident)
            continue
        if row['status'] != 'bound' or not bindings:
            raise ValueError('bound requirement requires at least one binding')
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) != {'path', 'expected'}:
                raise ValueError('binding requires only path and expected')
            if not _same(_value_at(request['spec'], binding['path']), binding['expected']):
                raise ValueError('binding value differs from spec: ' + ident)
            if quantity_diagnostics:
                comparison = _quantity_check(quote, binding, shared_unit_hz_ranges=task.get('quantity_range_mode')=='shared_unit_hz_v1')
                if comparison is not None:
                    quantity_checks.append({'requirement_id': ident, **comparison})
    gaps = []
    start = None
    for i, covered in enumerate(quoted + [True]):
        if not covered and start is None:
            start = i
        elif covered and start is not None:
            segment = source[start:i]
            if any(c.isalnum() for c in segment):
                gaps.append({'start': start, 'end': i, 'text': segment})
            start = None
    result = {'status': 'unresolved_requirements' if unresolved else 'declared_analysis_pending' if derived else 'bindings_consistent',
            'declared_requirements': len(rows), 'unresolved_ids': unresolved,
            'source_text_unquoted_spans': gaps, 'ambiguous_quote_ids': ambiguous,
            'limits': ['agent may omit or misunderstand requirements',
                       'matching a spec field does not prove a suitable acceptance test',
                       'unquoted spans are a review aid; quoted text is not necessarily understood or tested',
                       'source_text may be a transcription of an image, not the image itself']}
    if quantity_diagnostics:
        result['numeric_binding_checks'] = quantity_checks
        result['numeric_binding_warnings'] = [x for x in quantity_checks if not x['matches']]
        result['limits'].append('numeric checks cover only simple single Hz or ohm literals, are advisory and do not validate their semantic role or completeness')
    if derived:
        result['pending_rc_frequency_response_ids'] = derived
        result['limits'].append('caller-assigned derived requirements are pending until the separate analysis completes')
    return result
