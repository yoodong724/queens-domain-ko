#!/usr/bin/env python3
"""Assemble the build 26356968 package from an externally supplied payload."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STAMP = (2026, 11, 2, 0, 0, 0)
EXPECTED_ZIP = "baf2777c9f5e6c8e0c6f8c78c63f97413365be0ccf95e68dfa241c22010f3864"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(payload_path, output):
    manifest_bytes = (ROOT / "packaging/manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    operation = manifest["operations"][0]
    payload = payload_path.read_bytes()
    if digest(payload) != operation["payload_sha256"]:
        raise ValueError("payload SHA-256 does not match the manifest")
    runtime = ROOT / "project/tools/packaging-runtime/KoreanPatch"
    entries = {
        "KoreanPatch/LICENSE-Hahmlet-OFL.txt": (ROOT / "packaging/LICENSE-Hahmlet-OFL.txt").read_bytes(),
        "KoreanPatch/README.ko.txt": (ROOT / "packaging/README.ko.txt").read_bytes(),
        "KoreanPatch/install.cmd": (runtime / "install.cmd").read_bytes(),
        "KoreanPatch/manifest.json": manifest_bytes,
        "KoreanPatch/" + operation["payload"]: payload,
        "KoreanPatch/restore.cmd": (runtime / "restore.cmd").read_bytes(),
        "KoreanPatch/tools/KoreanPatch.ps1": (runtime / "tools/KoreanPatch.ps1").read_bytes(),
    }
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC verification failed")
    actual = digest(output.read_bytes())
    print("ZIP SHA-256:", actual)
    if EXPECTED_ZIP is not None:
        print("matches released bytes:", actual == EXPECTED_ZIP)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.payload, args.out)


if __name__ == "__main__":
    main()
