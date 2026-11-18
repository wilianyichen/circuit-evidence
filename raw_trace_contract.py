"""Check that the traces required by a measurement exist in a saved LTspice RAW.

The caller supplies exact trace names after inspecting the originating circuit.
This does not infer subcircuit aliases or validate the meaning of a trace.
"""
import argparse
import hashlib
import json
from pathlib import Path
from spicelib import RawRead


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check(raw_path: Path, required: list[str]) -> dict:
    path = raw_path.resolve(strict=True)
    before = file_sha256(path)
    names = RawRead(str(path), traces_to_read=[]).get_trace_names()
    index = {}
    for name in names:
        index.setdefault(name.casefold(), []).append(name)
    if not required or any(not name.strip() for name in required):
        raise ValueError('at least one nonempty exact trace name is required')
    if len({name.casefold() for name in required}) != len(required):
        raise ValueError('required trace names must be unique ignoring case')
    resolved, missing, ambiguous = {}, [], {}
    for name in required:
        matches = index.get(name.casefold(), [])
        if not matches:
            missing.append(name)
        elif len(matches) != 1:
            ambiguous[name] = matches
        else:
            resolved[name] = matches[0]
    after = file_sha256(path)
    if before != after:
        raise RuntimeError('RAW changed during inspection')
    return {'status': 'complete' if not missing and not ambiguous else 'missing_or_ambiguous',
            'raw_path': str(path), 'raw_sha256': before, 'required': required,
            'resolved': resolved, 'missing': missing, 'ambiguous': ambiguous,
            'scope': 'trace names exist; no verification of physical or semantic meaning'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True, type=Path)
    parser.add_argument('--require', required=True, action='append', dest='required')
    args = parser.parse_args()
    try:
        result = check(args.raw, args.required)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
