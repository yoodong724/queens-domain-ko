"""Five independent tools. There is deliberately no next-stage operation."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .checks import under, validate_targets
from .contracts import (CATALOG_FORMAT, DEFAULT_CONTEXT, SECTIONS, config, load_canonical,
                        load_catalog, load_translations, seal_catalog, translation_template,
                        unit_id, validate_catalog)
from .core import (ToolError, bounded_read, digest, ensure_new, load_json, pretty, require,
                   revision, safe_absolute, safe_relative, write_new_files, write_new_json,
                   write_new_tree)
from .json_object import JsonDocument, PatchError


def document(raw: bytes, name: str) -> JsonDocument:
    try:
        return JsonDocument(raw)
    except (PatchError, RecursionError) as exc:
        raise ToolError("ADAPTER_REJECTED", str(exc), {"file": name}) from exc


def make_catalog(root: Path, selection: dict) -> dict:
    config(selection)
    root = safe_absolute(root)
    require(root.is_dir(), "SOURCE_NOT_FOUND", str(root))
    files, units, arrays, excluded = [], [], [], []
    for name in selection["files"]:
        raw = bounded_read(safe_relative(root, name))
        doc = document(raw, name)
        require(doc.apply({}) == raw, "ROUNDTRIP_FAILED", name)
        files.append({"path": name, "sha256": digest(raw), "size": len(raw)})
        arrays += [{"file": name, "pointer": p} for p in doc.skipped_arrays]
        for ptr, (_, _, text) in doc.spans.items():
            if (not any(under(ptr, p) for p in selection["include_prefixes"])
                    or any(under(ptr, p) for p in selection["exclude_prefixes"])):
                excluded.append({"file": name, "pointer": ptr})
                continue
            ctx = copy.deepcopy(DEFAULT_CONTEXT)
            matches = [(len(k.split("#", 1)[1]), v) for k, v in selection["context"].items()
                       if k.split("#", 1)[0] == name and under(ptr, k.split("#", 1)[1])]
            if matches:
                ctx = copy.deepcopy(max(matches, key=lambda x: x[0])[1])
            rules = copy.deepcopy(selection["constraints"])
            if ctx["max_chars"] is not None:
                rules["max_chars"] = ctx["max_chars"]
            units.append({"id": unit_id(name, ptr), "file": name, "pointer": ptr, "source": text,
                          "source_hash": digest(text.encode("utf-8")), "context": ctx,
                          "context_hash": revision(ctx), "constraints": rules})
    require(bool(units), "NO_TRANSLATABLE_UNITS", "선택한 객체 문자열이 없습니다. 배열은 지원하지 않습니다.")
    cat = seal_catalog({"format": CATALOG_FORMAT, "adapter": "json-object-v1", "selection": copy.deepcopy(selection),
                        "files": files, "units": units, "skipped_arrays": arrays, "excluded_strings": excluded})
    return validate_catalog(cat)


def extract(root: Path, config_path: Path, out: Path, template_out: Path | None = None) -> dict:
    out = ensure_new(out, forbidden_roots=(root,), forbidden_files=(config_path,))
    if template_out is not None:
        template_out = ensure_new(template_out, forbidden_roots=(root,), forbidden_files=(config_path,))
        require(template_out != out, "OUTPUT_COLLISION", "catalog와 번역 양식 출력 경로가 같습니다.")
    cat = make_catalog(root, load_json(config_path))
    outputs = {out: pretty(cat)}
    if template_out is not None:
        outputs[template_out] = pretty(translation_template(cat))
    write_new_files(outputs)
    return {"ok": True, "tool": "extract", "catalog": str(out), "source_revision": cat["source_revision"],
            "units": len(cat["units"]), "files": len(cat["files"]), "skipped_arrays": cat["skipped_arrays"],
            "excluded_strings": len(cat["excluded_strings"]), "originals_written": False,
            "noop_roundtrip": "byte_identical", "translation_template": str(template_out) if template_out else None,
            "notice": "추출 가능한 문자열 목록이며 실제 번역 대상·장면 순서를 자동 판정하지 않습니다."}


def check_translation(catalog: dict, translations: dict, canonical: dict,
                      canonical_revision: str | None, ignored: list[dict], *, complete: bool) -> dict:
    supplied = {r["id"] for r in translations["translations"]}
    ready = {r["id"]: r["target"] for r in translations["translations"] if isinstance(r["target"], str)}
    pending = sorted(supplied - set(ready))
    missing = sorted({u["id"] for u in catalog["units"]} - supplied)
    selected = [u for u in catalog["units"] if u["id"] in ready]
    canon = {**canonical, **{k: [x for x in canonical[k] if x["status"] == "approved"] for k in SECTIONS}}
    result = validate_targets({"units": selected, "canonical": canon}, ready)
    result.update({"tool": "check", "source_revision": catalog["source_revision"],
                   "translations_revision": revision(translations), "canonical_revision": canonical_revision,
                   "complete_required": complete,
                   "coverage": {"catalog_units": len(catalog["units"]), "provided_rows": len(supplied),
                                "checked_units": len(selected), "pending_ids": pending, "missing_ids": missing},
                   "excluded_canonical_records": ignored,
                   "not_checked": result["not_checked"] + ["approval", "review_independence", "source_files_current_on_disk"]})
    for uid in pending:
        result["errors"].append({"code": "INCOMPLETE_TRANSLATION", "unit_id": uid, "message": "target=null은 미작성 값입니다."})
    if complete:
        for uid in missing:
            result["errors"].append({"code": "MISSING_TRANSLATION", "unit_id": uid, "message": "catalog에 대한 결과가 없습니다."})
    if not selected:
        result["errors"].append({"code": "NO_TRANSLATIONS", "unit_id": None, "message": "실제로 검사한 번역이 없습니다."})
    if translations.get("canonical_revision") is not None and canonical_revision is not None:
        if translations["canonical_revision"] != canonical_revision:
            result["errors"].append({"code": "STALE_CANONICAL", "unit_id": None,
                                     "message": "번역에 기록된 canonical_revision과 제공 기준이 다릅니다."})
    if canonical_revision is None:
        result["warnings"].append({"code": "CANONICAL_NOT_PROVIDED", "unit_id": None,
                                    "message": "용어집을 제공하지 않아 용어 기준 검사를 수행하지 않았습니다."})
        result["not_checked"].append("canonical_terms")
    elif translations.get("canonical_revision") is None:
        result["warnings"].append({"code": "UNBOUND_CANONICAL", "unit_id": None,
                                    "message": "제공한 기준으로 검사했으나 번역이 사용한 기준 버전은 기록되어 있지 않습니다."})
    if ignored:
        result["warnings"].append({"code": "NON_APPROVED_CANONICAL_IGNORED", "unit_id": None,
                                    "message": f"승인 상태가 아닌 기준 {len(ignored)}개를 검사에서 제외했습니다."})
    result["passed"] = not result["errors"]
    result["ok"] = result["passed"]
    result["notice"] = "부분 검사 통과를 전체 번역 완료·언어 검수·게임 QA 통과로 해석하지 마십시오. 상태는 변경하지 않습니다."
    return result


def check(catalog_path: Path, translations_path: Path, canonical_path: Path | None,
          out: Path | None, *, complete: bool = False) -> dict:
    if out:
        ensure_new(out, forbidden_files=(catalog_path, translations_path),
                   forbidden_roots=(canonical_path,) if canonical_path and canonical_path.is_dir() else ())
    cat = load_catalog(catalog_path)
    tr = load_translations(translations_path, cat, allow_pending=True)
    c, cr, ignored = load_canonical(canonical_path)
    result = check_translation(cat, tr, c, cr, ignored, complete=complete)
    if out:
        write_new_json(out, result)
    return result


def inject(root: Path, catalog_path: Path, translations_path: Path, out_dir: Path) -> dict:
    root = safe_absolute(root)
    out_dir = ensure_new(out_dir, forbidden_roots=(root,))
    # Inputs cannot be inside a not-yet-existing output directory.
    cat = load_catalog(catalog_path)
    tr = load_translations(translations_path, cat, allow_pending=False)
    targets = {r["id"]: r["target"] for r in tr["translations"]}
    outputs: dict[str, bytes] = {}
    hashes = []
    changed = 0
    for info in cat["files"]:
        name = info["path"]
        raw = bounded_read(safe_relative(root, name))
        require(digest(raw) == info["sha256"] and len(raw) == info["size"], "STALE_SOURCE", f"원본 바이트가 catalog와 다릅니다: {name}")
        doc = document(raw, name)
        updates = {}
        for u in cat["units"]:
            if u["file"] != name:
                continue
            require(u["pointer"] in doc.spans and doc.spans[u["pointer"]][2] == u["source"],
                    "SOURCE_LOCATION_MISMATCH", f"원문 위치/내용이 다릅니다: {u['id']}")
            if u["id"] in targets:
                updates[u["pointer"]] = targets[u["id"]]
                changed += targets[u["id"]] != u["source"]
        try:
            patched = doc.apply(updates)
        except PatchError as exc:
            raise ToolError("ADAPTER_REJECTED", str(exc), {"file": name}) from exc
        outputs[name] = patched
        hashes.append({"path": name, "source_sha256": info["sha256"], "output_sha256": digest(patched)})
    # No technical-quality check, approval, review, or tracer gate is called here.
    write_new_tree(out_dir, outputs)
    return {"ok": True, "tool": "inject", "output_directory": str(out_dir), "source_revision": cat["source_revision"],
            "translations_revision": revision(tr), "provided_rows": len(targets), "changed_units": changed,
            "untouched_units": len(cat["units"]) - len(targets), "files": hashes, "originals_written": False,
            "not_checked": ["placeholders", "tags", "language_quality", "canonical_terms", "approval", "game_execution"],
            "notice": "새 디렉터리에는 선택한 리소스 파일만 있습니다. 게임 전체 사본·배포 패치가 아니며 검사/승인을 요구하지 않습니다."}


def lookup(canonical_path: Path, query: str, section: str, status: str, limit: int) -> dict:
    require(query.strip(), "INVALID_QUERY", "빈 검색어는 허용하지 않습니다.")
    require(section in (*SECTIONS, "style", "all"), "SCHEMA_ERROR", "section")
    require(status in ("all", "approved", "proposed", "unknown", "rejected", "deprecated"), "SCHEMA_ERROR", "status")
    require(type(limit) is int and 1 <= limit <= 100, "INVALID_LIMIT", "limit은 1~100입니다.")
    c, cr, _ = load_canonical(canonical_path)
    found = []
    q = query.casefold()
    for k in SECTIONS:
        if section not in (k, "all"):
            continue
        for row in c[k]:
            if status not in ("all", row["status"]):
                continue
            if q in pretty(row).decode("utf-8").casefold():
                found.append({"section": k, "record": row})
    if section in ("style", "all") and q in c["style"].casefold():
        # style.md has no approval status; a status-filtered query omits it.
        if status == "all":
            found.append({"section": "style", "record": c["style"]})
    return {"ok": True, "tool": "lookup", "canonical_revision": cr, "query": query, "status": status,
            "matches": found[:limit], "total_matches": len(found), "truncated": len(found) > limit,
            "notice": "부분문자열 검색 결과입니다. 적용 범위·승인 상태는 직접 확인하십시오. 기준은 수정하지 않습니다."}


def diff(old_path: Path, new_path: Path, out: Path | None) -> dict:
    if out:
        ensure_new(out, forbidden_files=(old_path, new_path))
    old, new = load_catalog(old_path), load_catalog(new_path)
    left, right = ({u["id"]: u for u in c["units"]} for c in (old, new))
    rows = []
    counts: dict[str, int] = {}
    for uid in sorted(left.keys() | right.keys()):
        a, b = left.get(uid), right.get(uid)
        changes = []
        if a is None:
            state = "added"
        elif b is None:
            state = "removed"
        else:
            changes = [k for k in ("source", "context", "constraints") if a[k] != b[k]]
            state = "source_changed" if "source" in changes else "context_or_constraint_changed" if changes else "unchanged"
        counts[state] = counts.get(state, 0) + 1
        rows.append({"id": uid, "file": (b or a)["file"], "pointer": (b or a)["pointer"],
                     "status": state, "changed_fields": changes,
                     "old_source": a["source"] if a else None, "new_source": b["source"] if b else None})
    left_f, right_f = ({f["path"]: f["sha256"] for f in c["files"]} for c in (old, new))
    file_changes = [{"path": p, "old_sha256": left_f.get(p), "new_sha256": right_f.get(p)}
                    for p in sorted(left_f.keys() | right_f.keys()) if left_f.get(p) != right_f.get(p)]
    result = {"ok": True, "tool": "diff", "old_revision": old["source_revision"], "new_revision": new["source_revision"],
              "counts": counts, "units": rows, "file_changes": file_changes,
              "not_checked": ["canonical_changes", "semantic_dependencies", "renamed_or_moved_equivalence"],
              "notice": "경로·위치 기반 비교입니다. 이동은 삭제+추가로 표시하며 번역을 자동 재사용하지 않습니다."}
    if out:
        write_new_json(out, result)
    return result
