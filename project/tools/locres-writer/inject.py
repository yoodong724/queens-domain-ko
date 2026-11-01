#!/usr/bin/env python3
"""Apply a checked namespace/key target map and verify the entire v3 result."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import locres_reader


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate target key: ' + key)
        result[key] = value
    return result


def read_targets(data):
    targets = json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique_pairs)
    if not isinstance(targets, dict):
        raise ValueError('target map must be an object')
    for key, value in targets.items():
        if not isinstance(value, str):
            raise ValueError('target must be a string: ' + key)
        if value == '':
            raise ValueError('empty target: ' + key)
        value.encode('utf-8')
    return targets


def index_entries(observation):
    entries = {(item['namespace'], item['key']): item for item in observation['entries']}
    joined = {namespace + '/' + key: (namespace, key) for namespace, key in entries}
    if len(joined) != len(entries):
        raise ValueError('ambiguous namespace/key joining')
    # The R01 reader records each nonempty namespace in the entries, and also
    # its total count. A namespace with no keys cannot be compared by it.
    if len({namespace for namespace, key in entries}) != observation['namespace_count']:
        raise ValueError('unsupported empty or repeated namespace in locres')
    return entries, joined


def verify(before, after, targets):
    old, joined = index_entries(before)
    new, _ = index_entries(after)
    if before['namespace_count'] != after['namespace_count'] or old.keys() != new.keys():
        raise ValueError('verification failed: namespace/key coverage differs')
    for pair, original in old.items():
        result = new[pair]
        for field in ('ue_namespace_hash', 'ue_key_hash', 'ue_source_string_hash'):
            if original[field] != result[field]:
                raise ValueError('verification failed: UE hash differs for ' + '/'.join(pair))
        expected = targets.get('/'.join(pair), original['source'])
        if result['source'] != expected:
            raise ValueError('verification failed: value differs for ' + '/'.join(pair))
    return sum(new[pair]['source'] != original['source'] for pair, original in old.items())


def inject(source, expected_hash, target_path, expected_target_hash, writer, output):
    if os.path.lexists(output):
        raise FileExistsError('output already exists: ' + str(output))
    source_bytes = source.read_bytes()
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_hash) or digest(source_bytes) != expected_hash.lower():
        raise ValueError('source fingerprint mismatch')
    target_bytes = target_path.read_bytes()
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_target_hash) or digest(target_bytes) != expected_target_hash.lower():
        raise ValueError('target fingerprint mismatch')
    targets = read_targets(target_bytes)

    # Retain the source snapshot, validated target values and candidate;
    # the caller can audit them and clean up with the project's other scratch data.
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.work-', dir=output.parent))
    source_copy = stage / 'source.locres'
    source_copy.write_bytes(source_bytes)
    map_copy = stage / 'targets.json'
    map_copy.write_text(json.dumps(targets, ensure_ascii=False), encoding='utf-8')
    before = locres_reader.read(source_copy)
    old, joined = index_entries(before)
    absent = set(targets) - set(joined)
    if absent:
        raise ValueError('target key not found: ' + sorted(absent)[0])

    candidate = stage / 'candidate.locres'
    process = subprocess.run(['dotnet', str(writer), str(source_copy), str(map_copy), str(candidate)],
                             capture_output=True, text=True)
    if process.returncode:
        raise ValueError('writer failed: ' + process.stderr.strip())
    after = locres_reader.read(candidate)
    changed = verify(before, after, targets)
    candidate_hash = digest(candidate.read_bytes())
    # A same-directory hard link publishes the exact verified inode without
    # replacing an existing output; link creation itself is atomic.
    os.link(candidate, output)
    if digest(output.read_bytes()) != candidate_hash:
        raise ValueError('verification failed: published fingerprint differs')
    return {'source_sha256': digest(source_bytes), 'targets_sha256': digest(target_bytes),
            'output_sha256': candidate_hash, 'entries_verified': len(old),
            'namespaces_verified': before['namespace_count'], 'targets_verified': len(targets),
            'values_changed': changed, 'work_directory': str(stage)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'targets', 'writer', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--targets-sha256', required=True)
    args = parser.parse_args()
    try:
        result = inject(args.source, args.source_sha256, args.targets, args.targets_sha256, args.writer, args.out)
    except (OSError, ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
