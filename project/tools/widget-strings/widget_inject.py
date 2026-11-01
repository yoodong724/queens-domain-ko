#!/usr/bin/env python3
"""Build a checked pair for this game's fixed VirtualKeyboard asset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import widget_verify


ASSET_SHA = '9ca713beeef9004a3666be3ea7d26ae6282930808a1fbfb49b602beaa057aac4'
EXP_SHA = '5f90cd36a8c0c685e8cab3030395a372462f4d33d9b6921a4a9fcd5f2b4abb90'
ASSET_PATH = 'QueensDomain/Content/UI/Widgets/VirtualKeyboard'
SPEC = {'ConfirmKey': 67, 'ClearButton': 66}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key: ' + key)
        out[key] = value
    return out


def parse_proposal(raw, expected_hash):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_hash) or digest(raw) != expected_hash.lower():
        raise ValueError('proposal fingerprint mismatch')
    data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_pairs)
    if not isinstance(data, dict) or data.get('format') != 'queens-domain-widget-text-v1':
        raise ValueError('unexpected proposal format')
    if (data.get('source_asset') != ASSET_PATH or data.get('source_uasset_sha256') != ASSET_SHA
            or data.get('source_uexp_sha256') != EXP_SHA):
        raise ValueError('proposal source does not match fixed asset')
    entries = data.get('entries')
    if not isinstance(entries, list) or len(entries) != 2:
        raise ValueError('proposal must contain exactly two entries')
    sources = {}
    targets = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('proposal entry must be an object')
        name = entry.get('object')
        if name not in SPEC or name in targets:
            raise ValueError('unexpected or duplicate proposal object')
        if entry.get('export_index') != SPEC[name] or entry.get('property') != 'CharacterToDisplay':
            raise ValueError('proposal entry does not match fixed source: ' + name)
        source = entry.get('source')
        if not isinstance(source, str) or not source or '\0' in source:
            raise ValueError('source must be a nonempty string without NUL: ' + name)
        source.encode('ascii')
        sources[name] = source
        target = entry.get('target')
        if not isinstance(target, str) or not target or '\0' in target:
            raise ValueError('target must be a nonempty string without NUL: ' + name)
        target.encode('utf-16le')
        targets[name] = target
    if set(targets) != set(SPEC):
        raise ValueError('proposal is missing a target')
    if '\r' in targets['ConfirmKey'] or '\n' in targets['ConfirmKey']:
        raise ValueError('confirm target must have one line')
    rows = targets['ClearButton'].split('\r\n')
    if len(rows) != 3 or any(not row or '\r' in row or '\n' in row for row in rows):
        raise ValueError('clear target must preserve three CRLF-separated rows')
    return sources, targets


def inspect(inspector, source, destination, log):
    process = subprocess.run(['dotnet', str(inspector), str(source), str(destination)], capture_output=True, text=True)
    log.write_text(process.stdout + process.stderr, encoding='utf-8')
    if process.returncode != 0 or 'raw=0' not in process.stdout or 'binaryEqual=True' not in process.stdout:
        raise ValueError('inspection failed: ' + source.name)
    return json.loads(destination.read_text(encoding='utf-8'))


def inject(asset_path, proposal_path, expected_hash, writer, inspector, out):
    if os.path.lexists(out):
        raise FileExistsError('output already exists: ' + str(out))
    if asset_path.suffix != '.uasset':
        raise ValueError('source must be a .uasset with a sibling .uexp')
    asset_bytes = asset_path.read_bytes()
    exp_bytes = asset_path.with_suffix('.uexp').read_bytes()
    if digest(asset_bytes) != ASSET_SHA or digest(exp_bytes) != EXP_SHA:
        raise ValueError('source fingerprint mismatch')
    proposal_bytes = proposal_path.read_bytes()
    sources, targets = parse_proposal(proposal_bytes, expected_hash)
    if not writer.is_file() or not inspector.is_file():
        raise ValueError('writer or inspector not found')

    out.mkdir()
    work = out / 'work'
    input_dir = work / 'input'
    candidate_dir = work / 'candidate'
    input_dir.mkdir(parents=True)
    candidate_dir.mkdir()
    source = input_dir / 'VirtualKeyboard.uasset'
    source.write_bytes(asset_bytes)
    source.with_suffix('.uexp').write_bytes(exp_bytes)
    (work / 'proposal.json').write_bytes(proposal_bytes)
    before = inspect(inspector, source, work / 'before.json', work / 'before-inspect.log')
    candidate = candidate_dir / 'VirtualKeyboard.uasset'
    process = subprocess.run(['dotnet', str(writer), str(source), str(candidate),
                              sources['ConfirmKey'], targets['ConfirmKey'],
                              sources['ClearButton'], targets['ClearButton']],
                             capture_output=True, text=True)
    (work / 'writer.log').write_text(process.stdout + process.stderr, encoding='utf-8')
    if process.returncode != 0:
        raise ValueError('writer failed: ' + process.stderr.strip())
    after = inspect(inspector, candidate, work / 'after.json', work / 'after-inspect.log')
    result_asset = candidate.read_bytes()
    result_exp = candidate.with_suffix('.uexp').read_bytes()
    checked = widget_verify.verify(before, after, asset_bytes, result_asset, exp_bytes, result_exp, sources, targets)

    staging = out / 'staging'
    destination = staging / 'QueensDomain/Content/UI/Widgets'
    destination.mkdir(parents=True)
    (destination / 'VirtualKeyboard.uasset').write_bytes(result_asset)
    (destination / 'VirtualKeyboard.uexp').write_bytes(result_exp)
    if (destination / 'VirtualKeyboard.uasset').read_bytes() != result_asset or (destination / 'VirtualKeyboard.uexp').read_bytes() != result_exp:
        raise ValueError('verification failed: copied candidate differs')
    staging.rename(out / 'packroot')
    result = {'source_uasset_sha256': ASSET_SHA, 'source_uexp_sha256': EXP_SHA,
              'proposal_sha256': digest(proposal_bytes), 'uasset_sha256': digest(result_asset),
              'uexp_sha256': digest(result_exp), **checked,
              'note': 'static candidate only; button event arguments change with target values; runtime and all-language effects unverified'}
    (out / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('asset', 'proposal', 'writer', 'inspector', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--proposal-sha256', required=True)
    args = parser.parse_args()
    try:
        result = inject(args.asset, args.proposal, args.proposal_sha256, args.writer, args.inspector, args.out)
    except (OSError, ValueError, TypeError, KeyError, IndexError, UnicodeError, json.JSONDecodeError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
