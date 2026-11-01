#!/usr/bin/env python3
"""Extract targets from a fingerprinted CSV previously checked by locres_csv.py."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys


def convert(csv_path, expected_hash, output):
    data = csv_path.read_bytes()
    actual_hash = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_hash) or actual_hash != expected_hash.lower():
        raise ValueError('CSV fingerprint mismatch')
    reader = csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''), strict=True)
    if next(reader, None) != ['key', 'source', 'target']:
        raise ValueError('unexpected CSV columns')
    seen = set()
    targets = {}
    for row in reader:
        if len(row) != 3 or not row[0]:
            raise ValueError('invalid CSV row')
        key, source, target = row
        if key in seen:
            raise ValueError('duplicate CSV key: ' + key)
        seen.add(key)
        if target:
            targets[key] = target
    with output.open('x', encoding='utf-8', newline='') as f:
        json.dump(targets, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return {'csv_sha256': actual_hash, 'rows': len(seen), 'targets': len(targets),
            'targets_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', required=True, type=Path)
    parser.add_argument('--csv-sha256', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = convert(args.csv, args.csv_sha256, args.out)
    except (OSError, ValueError, UnicodeError, csv.Error) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
