#!/usr/bin/env python3
"""Insert a single BC3 mip into one of three verified game-over textures."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

TEXTURES = {
    'DeathScreenGAMEOVER': (
        'eb755a0f679fde66331c8ad72839926a6a4acfeefb8bb253b537c185a46bc15b',
        '0fcc450fd84fa3fe2d71abd025ce7772681556baa8b2f08540c84cc2ee0e75d3', 860),
    'DeathScreenRIPGRANDMA': (
        '69630f213fc4c25ff2c512c21ea816383cdedf881fd326c6409f4dc6586fec23',
        'a65c982ee1f44af58ce98b8dada24c654aeb12b4e22a87432ed7c9485abd94c2', 864),
    'ripgrandmalogo': (
        'b4d618b864b7a899213bfcc5715cd954cf20683bd131991f060069c82b9fcb4f',
        '38300c9ab52ed1c97f75f7c695b7ea20c744639ce3a23cec492572d287fa29be', 850),
}
WIDTH, HEIGHT = 1024, 256
PAYLOAD_SIZE = 262144
PIXEL_OFFSET = 296
def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_source(asset_path, uexp_path, texture):
    asset_sha256, uexp_sha256, asset_size = TEXTURES[texture]
    asset, uexp = asset_path.read_bytes(), uexp_path.read_bytes()
    if digest(asset) != asset_sha256:
        raise ValueError('source uasset sha256 mismatch')
    if digest(uexp) != uexp_sha256:
        raise ValueError('source uexp sha256 mismatch')
    if len(asset) != asset_size or len(uexp) != 262468:
        raise ValueError('source size mismatch')
    if uexp.count(b'PF_DXT5\0') != 1 or uexp[256:264] != b'PF_DXT5\0':
        raise ValueError('source texture format mismatch')
    if struct.unpack_from('<III', uexp, 240) != (WIDTH, HEIGHT, 1):
        raise ValueError('source dimensions mismatch')
    if struct.unpack_from('<II', uexp, 264) != (0, 1):
        raise ValueError('source mip count mismatch')
    if struct.unpack_from('<IIIIQ', uexp, 272) != (1, 72, PAYLOAD_SIZE, PAYLOAD_SIZE, len(asset) + PIXEL_OFFSET):
        raise ValueError('source mip descriptor mismatch')
    if struct.unpack_from('<III', uexp, PIXEL_OFFSET + PAYLOAD_SIZE) != (WIDTH, HEIGHT, 1):
        raise ValueError('source mip dimensions mismatch')
    return asset, uexp


def read_dds(path, expected_sha):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha):
        raise ValueError('DDS sha256 must contain 64 hexadecimal characters')
    data = path.read_bytes()
    if digest(data) != expected_sha.lower():
        raise ValueError('DDS sha256 mismatch')
    if len(data) != 128 + PAYLOAD_SIZE:
        raise ValueError('DDS length mismatch')
    if data[:4] != b'DDS ' or struct.unpack_from('<I', data, 4)[0] != 124:
        raise ValueError('DDS header invalid')
    flags, height, width, size, depth, mip_count = struct.unpack_from('<6I', data, 8)
    required_flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    if flags & required_flags != required_flags:
        raise ValueError('DDS required flags missing')
    if (width, height, size, depth, mip_count) != (WIDTH, HEIGHT, PAYLOAD_SIZE, 0, 1):
        raise ValueError('DDS dimensions, mip count or size mismatch')
    if struct.unpack_from('<II', data, 76) != (32, 4) or data[84:88] != b'DXT5':
        raise ValueError('DDS must be legacy DXT5/BC3')
    caps, caps2 = struct.unpack_from('<II', data, 108)
    if not caps & 0x1000 or caps2 != 0:
        raise ValueError('DDS must contain one 2D texture')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--texture', choices=TEXTURES, required=True)
    parser.add_argument('--asset', type=Path, required=True)
    parser.add_argument('--uexp', type=Path, required=True)
    parser.add_argument('--dds', type=Path, required=True)
    parser.add_argument('--dds-sha256', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    asset, original = read_source(args.asset, args.uexp, args.texture)
    dds = read_dds(args.dds, args.dds_sha256)
    payload = dds[128:]
    modified = original[:PIXEL_OFFSET] + payload + original[PIXEL_OFFSET + PAYLOAD_SIZE:]
    try:
        args.output_dir.mkdir()
    except FileExistsError as exc:
        raise ValueError('output already exists') from exc
    target = args.output_dir / 'packroot/QueensDomain/Content/UI/GameOver'
    target.mkdir(parents=True)
    asset_out, uexp_out = target / (args.texture + '.uasset'), target / (args.texture + '.uexp')
    asset_out.write_bytes(asset)
    uexp_out.write_bytes(modified)
    if asset_out.read_bytes() != asset or uexp_out.read_bytes() != modified:
        raise OSError('written output did not match verified bytes')
    summary = {
        'texture': args.texture,
        'source_uasset_sha256': digest(asset), 'source_uexp_sha256': digest(original),
        'input_dds_sha256': digest(dds), 'input_bc3_sha256': digest(payload),
        'output_uasset_sha256': digest(asset), 'output_uexp_sha256': digest(modified),
        'format': 'DXT5/BC3', 'width': WIDTH, 'height': HEIGHT, 'mip_count': 1,
        'uexp_payload_offset': PIXEL_OFFSET, 'payload_size': PAYLOAD_SIZE,
        'output_scope': 'packroot/QueensDomain/Content/UI/GameOver/' + args.texture,
    }
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        print('error:', exc, file=sys.stderr)
        sys.exit(1)
