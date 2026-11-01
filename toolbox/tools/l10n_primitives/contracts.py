"""Small data contracts, independent of approvals, jobs, sessions, or databases."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .checks import check_canonical
from .core import (bounded_read, digest, fields, load_json, nonempty, relative_name,
                   require, revision, safe_absolute, safe_relative)

CATALOG_FORMAT = "l10n-toolbox/catalog-v1"
TRANSLATION_FORMAT = "l10n-toolbox/translations-v1"
DEFAULT_CONSTRAINTS = {"placeholders": "simple-v1", "tag_policy": "strict-sequence",
                       "preserve_newline_count": True, "max_chars": None}
DEFAULT_CONTEXT = {"scene_id": None, "speaker_id": None, "status": "unknown", "note": "",
                   "blocking_questions": [], "max_chars": None}
SECTIONS = ("glossary", "characters", "scenes", "decisions")


def pointer(value: Any) -> None:
    require(isinstance(value, str) and (value == "" or value.startswith("/"))
            and not re.search(r"~(?![01])", value), "SCHEMA_ERROR", "올바른 JSON Pointer가 필요합니다.")


def sha_string(value: Any) -> None:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            "SCHEMA_ERROR", "64자 소문자 SHA-256이 필요합니다.")


def constraints(value: Any) -> None:
    fields(value, set(DEFAULT_CONSTRAINTS))
    require(value["placeholders"] in ("simple-v1", "none"), "SCHEMA_ERROR", "placeholders")
    require(value["tag_policy"] in ("strict-sequence", "none"), "SCHEMA_ERROR", "tag_policy")
    require(type(value["preserve_newline_count"]) is bool, "SCHEMA_ERROR", "preserve_newline_count")
    require(value["max_chars"] is None or (type(value["max_chars"]) is int and value["max_chars"] > 0),
            "SCHEMA_ERROR", "max_chars")


def context(value: Any) -> None:
    fields(value, set(DEFAULT_CONTEXT))
    require(value["status"] in ("unknown", "confirmed", "not_applicable"), "SCHEMA_ERROR", "context.status")
    for k in ("speaker_id", "scene_id"):
        require(value[k] is None or (isinstance(value[k], str) and bool(value[k])), "SCHEMA_ERROR", k)
    require(isinstance(value["note"], str), "SCHEMA_ERROR", "context.note")
    require(isinstance(value["blocking_questions"], list)
            and all(isinstance(x, str) and bool(x.strip()) for x in value["blocking_questions"]), "SCHEMA_ERROR", "blocking_questions")
    require(value["max_chars"] is None or (type(value["max_chars"]) is int and value["max_chars"] > 0),
            "SCHEMA_ERROR", "context.max_chars")


def config(value: Any) -> None:
    fields(value, {"files", "include_prefixes", "exclude_prefixes", "context", "constraints"})
    require(isinstance(value["files"], list) and bool(value["files"]), "CONFIG_INCOMPLETE", "files를 명시하십시오.")
    for name in value["files"]:
        relative_name(name)
        require(name.lower().endswith(".json"), "UNSUPPORTED_ADAPTER", ".json 파일만 지원합니다.")
    require(len({x.casefold() for x in value["files"]}) == len(value["files"]), "DUPLICATE_FILE", "파일명 중복입니다.")
    for k in ("include_prefixes", "exclude_prefixes"):
        require(isinstance(value[k], list), "SCHEMA_ERROR", k)
        for x in value[k]:
            pointer(x)
    require(bool(value["include_prefixes"]), "CONFIG_INCOMPLETE", 'include_prefixes를 명시하십시오. 전체 선택은 [""]입니다.')
    constraints(value["constraints"])
    require(isinstance(value["context"], dict), "SCHEMA_ERROR", "context")
    for ref, item in value["context"].items():
        require(isinstance(ref, str) and "#" in ref, "SCHEMA_ERROR", "문맥 위치는 file.json#/pointer 형식입니다.")
        file_name, ptr = ref.split("#", 1)
        require(file_name in value["files"], "SCHEMA_ERROR", f"문맥에 알 수 없는 파일: {file_name}")
        pointer(ptr)
        context(item)


def unit_id(file_name: str, ptr: str) -> str:
    # Same location-based identifier as the original conversation kit v0.1.0.
    return "u_" + digest((file_name + "\x00" + ptr).encode("utf-8"))[:24]


def seal_catalog(value: dict) -> dict:
    return {**value, "source_revision": revision(value)}


def validate_catalog(value: Any) -> dict:
    fields(value, {"format", "adapter", "selection", "files", "units", "skipped_arrays", "excluded_strings", "source_revision"})
    require(value["format"] == CATALOG_FORMAT and value["adapter"] == "json-object-v1", "UNSUPPORTED_FORMAT", "지원하지 않는 catalog입니다.")
    sha_string(value["source_revision"])
    require(revision({k: v for k, v in value.items() if k != "source_revision"}) == value["source_revision"],
            "CATALOG_HASH_MISMATCH", "catalog 내용과 source_revision이 다릅니다. 입력 변경 시 다시 추출하십시오.")
    config(value["selection"])
    require(isinstance(value["files"], list), "SCHEMA_ERROR", "files")
    names = []
    for f in value["files"]:
        fields(f, {"path", "sha256", "size"})
        relative_name(f["path"])
        sha_string(f["sha256"])
        require(type(f["size"]) is int and f["size"] >= 0, "SCHEMA_ERROR", "file.size")
        names.append(f["path"])
    require(names == value["selection"]["files"], "SCHEMA_ERROR", "files와 selection이 다릅니다.")
    require(isinstance(value["units"], list) and bool(value["units"]), "SCHEMA_ERROR", "빈 catalog는 지원하지 않습니다.")
    ids = set()
    for u in value["units"]:
        fields(u, {"id", "file", "pointer", "source", "source_hash", "context", "context_hash", "constraints"})
        pointer(u["pointer"])
        require(u["file"] in names, "SCHEMA_ERROR", "unit.file")
        require(isinstance(u["source"], str), "SCHEMA_ERROR", "unit.source")
        require(u["id"] == unit_id(u["file"], u["pointer"]), "INVALID_UNIT_ID", "위치와 ID가 다릅니다.")
        require(u["id"] not in ids, "DUPLICATE_ID", u["id"])
        ids.add(u["id"])
        require(u["source_hash"] == digest(u["source"].encode("utf-8")), "SOURCE_HASH_MISMATCH", u["id"])
        context(u["context"])
        require(u["context_hash"] == revision(u["context"]), "CONTEXT_HASH_MISMATCH", u["id"])
        constraints(u["constraints"])
    for k in ("skipped_arrays", "excluded_strings"):
        require(isinstance(value[k], list), "SCHEMA_ERROR", k)
        for item in value[k]:
            fields(item, {"file", "pointer"})
            require(item["file"] in names, "SCHEMA_ERROR", k + ".file")
            pointer(item["pointer"])
    return value


def load_catalog(path: Path) -> dict:
    return validate_catalog(load_json(path))


def translation_template(catalog: dict) -> dict:
    return {"format": TRANSLATION_FORMAT, "source_revision": catalog["source_revision"],
            "canonical_revision": None, "provenance": {},
            "translations": [{"id": u["id"], "source_hash": u["source_hash"], "target": None}
                             for u in catalog["units"]]}


def load_translations(path: Path, catalog: dict, *, allow_pending: bool) -> dict:
    value = load_json(path)
    fields(value, {"format", "source_revision", "translations"}, {"canonical_revision", "provenance", "notes"})
    require(value["format"] == TRANSLATION_FORMAT, "UNSUPPORTED_FORMAT", "지원하지 않는 번역 형식입니다.")
    require(value["source_revision"] == catalog["source_revision"], "STALE_CATALOG", "번역의 source_revision이 현재 catalog와 다릅니다.")
    if value.get("canonical_revision") is not None:
        sha_string(value["canonical_revision"])
    if "provenance" in value:
        require(isinstance(value["provenance"], dict), "SCHEMA_ERROR", "provenance")
    if "notes" in value:
        require(isinstance(value["notes"], str), "SCHEMA_ERROR", "notes")
    require(isinstance(value["translations"], list), "SCHEMA_ERROR", "translations")
    known = {u["id"]: u for u in catalog["units"]}
    seen = set()
    for row in value["translations"]:
        fields(row, {"id", "source_hash", "target"}, {"notes"})
        require(isinstance(row["id"], str) and row["id"] in known, "UNKNOWN_UNIT", str(row.get("id")))
        require(row["id"] not in seen, "DUPLICATE_ID", row["id"])
        seen.add(row["id"])
        require(row["source_hash"] == known[row["id"]]["source_hash"], "SOURCE_HASH_MISMATCH", row["id"])
        if row["target"] is None:
            require(allow_pending, "INCOMPLETE_TRANSLATION", f"미작성 target=null: {row['id']}")
        else:
            require(isinstance(row["target"], str) and len(row["target"]) <= 65536, "SCHEMA_ERROR", "target은 65,536 코드포인트 이하 문자열입니다.")
        if "notes" in row:
            require(isinstance(row["notes"], str), "SCHEMA_ERROR", "translation.notes")
    return value


def load_canonical(path: Path | None) -> tuple[dict, str | None, list[dict]]:
    if path is None:
        return {"schema_version": "0.1", "style": "(not supplied)", **{k: [] for k in SECTIONS}}, None, []
    path = safe_absolute(path)
    if path.is_dir():
        try:
            style = bounded_read(safe_relative(path, "style.md")).decode("utf-8-sig")
        except UnicodeError as exc:
            from .core import ToolError
            raise ToolError("INVALID_UTF8", "style.md는 UTF-8이어야 합니다.") from exc
        c = {"schema_version": "0.1", "style": style,
             **{k: load_json(safe_relative(path, k + ".json")) for k in SECTIONS}}
    else:
        c = load_json(path)
    fields(c, {"schema_version", "style", *SECTIONS})
    require(c["schema_version"] == "0.1", "UNSUPPORTED_FORMAT", "canonical.schema_version")
    nonempty(c["style"], "style")
    ignored = []
    approved = {"schema_version": "0.1", "style": c["style"]}
    for k in SECTIONS:
        require(isinstance(c[k], list), "SCHEMA_ERROR", k)
        seen = set()
        for row in c[k]:
            require(isinstance(row, dict), "SCHEMA_ERROR", k)
            identifier = nonempty(row.get("id"), k + ".id")
            require(identifier not in seen, "DUPLICATE_ID", identifier)
            seen.add(identifier)
            require(row.get("status") in ("approved", "proposed", "unknown", "rejected", "deprecated"), "SCHEMA_ERROR", identifier + ".status")
            if row["status"] != "approved":
                ignored.append({"section": k, "id": identifier, "status": row["status"]})
        approved[k] = [x for x in c[k] if x["status"] == "approved"]
    check_canonical(approved)
    # Return the complete content: lookup may inspect proposals; check filters them.
    return c, revision(c), ignored
