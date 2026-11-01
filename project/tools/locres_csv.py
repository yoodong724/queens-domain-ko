#!/usr/bin/env python3
"""Connect checked toolbox batches to an UnrealLocres CSV from a fixed locres."""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "toolbox/tools"))
from l10n_primitives.contracts import load_canonical, load_catalog, load_translations
from l10n_primitives.core import ToolError
from l10n_primitives.operations import check_translation


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compile_csv(locres, observation_path, csv_path, canonical_path, batches, output):
    observation_bytes = observation_path.read_bytes()
    observation = json.loads(observation_bytes)
    if observation["format"] != "queens-domain-locres-v3-observation":
        raise ValueError("unsupported observation format")
    if digest(locres.read_bytes()) != observation["locres_sha256"]:
        raise ValueError("locres fingerprint mismatch")

    original = {}
    key_namespaces = {}
    for entry in observation["entries"]:
        key = (entry["namespace"], entry["key"])
        if key in original or digest(entry["source"].encode("utf-8")) != entry["source_utf8_sha256"]:
            raise ValueError("duplicate or stale observed source")
        original[key] = entry["source"]
        key_namespaces.setdefault(entry["key"], set()).add(entry["namespace"])
    csv_keys = {f"{ns}/{key}": value for (ns, key), value in original.items()}
    if len(csv_keys) != len(original):
        raise ValueError("ambiguous UnrealLocres CSV key")
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["key", "source", "target"]:
            raise ValueError("unexpected CSV columns")
        rows = list(reader)
    by_key = {}
    for row in rows:
        key = row["key"]
        if key in by_key or key not in csv_keys or row["source"] != csv_keys[key] or row["target"] != "":
            raise ValueError("CSV source mismatch, duplicate, or nonempty target")
        by_key[key] = row
    if set(by_key) != set(csv_keys):
        raise ValueError("CSV and observation coverage differ")

    canonical, canonical_revision, ignored = load_canonical(canonical_path)
    used = set()
    for catalog_path, scope_path, translations_path in batches:
        catalog = load_catalog(catalog_path)
        translations = load_translations(translations_path, catalog, allow_pending=False)
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        if (scope["source_revision"] != catalog["source_revision"] or
            scope["canonical_revision"] != canonical_revision or
            translations.get("canonical_revision") != canonical_revision or
            scope["full_en_observation_sha256"] != digest(observation_bytes)):
            raise ValueError("batch revision mismatch")
        checked = check_translation(catalog, translations, canonical, canonical_revision, ignored, complete=True)
        if not checked["passed"]:
            raise ValueError("batch technical check failed")
        units = {unit["id"]: unit for unit in catalog["units"]}
        targets = {row["id"]: row["target"] for row in translations["translations"]}
        mappings = scope["mapping"]
        if len(mappings) != len(units) or {m["unit_id"] for m in mappings} != set(units):
            raise ValueError("scope does not cover the catalog exactly")
        for item in mappings:
            unit = units[item["unit_id"]]
            key = (item["namespace"], item["key"])
            pointer_key = unit["pointer"].rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
            if pointer_key != item["key"]:
                raise ValueError("scope key does not match catalog pointer")
            if key_namespaces.get(item["key"]) != {item["namespace"]}:
                raise ValueError("scope namespace is ambiguous or absent")
            if (key in used or key not in original or unit["source"] != original[key] or
                unit["source_hash"] != item["source_hash"]):
                raise ValueError("overlap or UE source mapping mismatch")
            used.add(key)
            by_key[f"{key[0]}/{key[1]}"]["target"] = targets[item["unit_id"]]

    with output.open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "source", "target"])
        writer.writeheader()
        writer.writerows(rows)
    return len(used), len(original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("locres", "observation", "csv", "canonical", "out"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--batch", nargs=3, action="append", required=True, type=Path,
                        metavar=("CATALOG", "SCOPE", "MERGED_TRANSLATIONS"))
    args = parser.parse_args()
    try:
        selected, total = compile_csv(args.locres, args.observation, args.csv,
                                      args.canonical, args.batch, args.out)
    except (OSError, ValueError, KeyError, TypeError, ToolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"selected": selected, "observed": total,
                      "notice": "기술 변환만 수행; 언어 검수·게임 표시·전체 범위 완료를 뜻하지 않음"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
