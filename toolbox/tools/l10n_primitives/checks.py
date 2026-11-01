"""Explicit prototype grammar checks, not a universal game markup parser."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from .core import fields, nonempty, require

BRACES = re.compile(r"\{\{|\}\}|\{(?:[A-Za-z_][A-Za-z0-9_.]*|[0-9]+)(?::[^{}\r\n]+)?\}")
PRINTF = re.compile(r"%%|%(?:[0-9]+\$)?[-+#0 ']*(?:[0-9]+|\*)?(?:\.(?:[0-9]+|\*))?(?:hh|ll|h|l|j|z|t|L)?[diuoxXfFeEgGaAcsp]")
TAGS = re.compile(r"</?[A-Za-z][^<>\r\n]*>|\[/?(?:b|i|u|color|size)(?:=[^\]\r\n]+)?\]|\[br\]")
CHECKS_VERSION = "simple-placeholders-tags-v1"


def scope_matches(scope: dict, unit: dict) -> bool:
    file_ok = not scope.get("files") or unit["file"] in scope["files"]
    prefixes = scope.get("pointer_prefixes", [])
    pointer_ok = not prefixes or any(under(unit["pointer"], p) for p in prefixes)
    scenes = scope.get("scene_ids", [])
    characters = scope.get("character_ids", [])
    return (file_ok and pointer_ok
            and (not scenes or unit["context"]["scene_id"] in scenes)
            and (not characters or unit["context"]["speaker_id"] in characters))


def under(pointer: str, prefix: str) -> bool:
    return prefix == "" or pointer == prefix or pointer.startswith(prefix + "/")


def relevant_terms(canonical: dict, units: list[dict]) -> list[dict]:
    result = []
    for term in canonical["glossary"]:
        if any(scope_matches(term["scope"], u)
               and any(form in u["source"] for form in term["source_forms"]) for u in units):
            result.append(term)
    return result


def check_canonical(c: dict) -> None:
    fields(c, {"schema_version", "glossary", "style", "characters", "scenes", "decisions"})
    require(c["schema_version"] == "0.1", "SCHEMA_ERROR", "지원하지 않는 canonical 버전입니다.")
    nonempty(c["style"], "style")
    for section in ("glossary", "characters", "scenes", "decisions"):
        require(isinstance(c[section], list), "SCHEMA_ERROR", f"{section}는 목록이어야 합니다.")
        ids = set()
        for record in c[section]:
            require(isinstance(record, dict), "SCHEMA_ERROR", section)
            identifier = nonempty(record.get("id"), f"{section}.id")
            require(identifier not in ids, "DUPLICATE_ID", identifier)
            ids.add(identifier)
            require(record.get("status") == "approved", "UNAPPROVED_CANONICAL",
                    f"확정되지 않은 항목은 proposals에 두십시오: {identifier}")
            require(isinstance(record.get("evidence"), list), "SCHEMA_ERROR", f"{identifier}.evidence")
            for entry in record["evidence"]:
                nonempty(entry, "evidence")
    for term in c["glossary"]:
        fields(term, {"id", "status", "source_forms", "target", "definition", "scope",
                      "enforcement", "evidence"}, {"forbidden_targets"})
        require(isinstance(term["source_forms"], list) and bool(term["source_forms"]),
                "SCHEMA_ERROR", "source_forms가 필요합니다.")
        for form in term["source_forms"]:
            nonempty(form, "source_form")
        nonempty(term["target"], "target")
        nonempty(term["definition"], "definition")
        require(term["enforcement"] in ("exact", "advisory"), "SCHEMA_ERROR", "enforcement")
        fields(term["scope"], {"files", "pointer_prefixes", "scene_ids", "character_ids"})
        for key, values in term["scope"].items():
            require(isinstance(values, list) and all(isinstance(v, str) for v in values),
                    "SCHEMA_ERROR", f"scope.{key}")
        require(isinstance(term.get("forbidden_targets", []), list)
                and all(isinstance(v, str) and v for v in term.get("forbidden_targets", [])),
                "SCHEMA_ERROR", "forbidden_targets")
    # Records stay flexible for game-specific relationships, but mandatory meaning remains explicit.
    for section in ("characters", "scenes", "decisions"):
        for record in c[section]:
            nonempty(record.get("guidance"), f"{section}.guidance")


def validate_targets(bundle: dict, targets: dict[str, str]) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []

    def report(code: str, unit: dict, message: str, warning: bool = False) -> None:
        (warnings if warning else errors).append({"code": code, "unit_id": unit["id"], "message": message})

    for u in bundle["units"]:
        src, dst = u["source"], targets[u["id"]]
        rules = u["constraints"]
        if u["context"]["blocking_questions"]:
            report("MISSING_CONTEXT", u, "미해결 필수 문맥: " + "; ".join(u["context"]["blocking_questions"]))
        if src and not dst.strip():
            report("EMPTY_TRANSLATION", u, "비어 있지 않은 원문에 빈 번역을 제출했습니다.")
        if not src and dst:
            report("EMPTY_SOURCE_EXPANSION", u, "빈 원문은 비워 두어야 합니다.")
        if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in dst):
            report("CONTROL_CHARACTER", u, "허용하지 않는 제어 문자입니다.")
        if rules["placeholders"] == "simple-v1":
            src_b, dst_b = BRACES.findall(src), BRACES.findall(dst)
            if Counter(src_b) != Counter(dst_b):
                report("PLACEHOLDER_MISMATCH", u, "중괄호 변수/이스케이프의 이름·형식·개수가 다릅니다.")
            # Unrecognized brace grammar must be configured via another adapter, not guessed.
            if any(c in BRACES.sub("", src) for c in "{}"):
                report("UNSUPPORTED_PLACEHOLDER_GRAMMAR", u, "원문에 ICU 등 지원하지 않는 중괄호 문법이 있습니다.")
            if any(c in BRACES.sub("", dst) for c in "{}"):
                report("UNSUPPORTED_PLACEHOLDER_GRAMMAR", u, "번역에 지원하지 않는 중괄호 문법이 있습니다.")
            sp, tp = PRINTF.findall(src), PRINTF.findall(dst)
            if Counter(sp) != Counter(tp):
                report("PRINTF_MISMATCH", u, "printf 변수의 형식·개수가 다릅니다.")
            sequential = lambda xs: [x for x in xs if x != "%%" and not re.match(r"%[0-9]+\$", x)]
            if sequential(sp) != sequential(tp):
                report("PRINTF_ORDER_MISMATCH", u, "위치 번호가 없는 printf 변수의 순서가 다릅니다.")
        if rules["tag_policy"] == "strict-sequence" and TAGS.findall(src) != TAGS.findall(dst):
            report("TAG_MISMATCH", u, "지원 태그의 내용·순서가 다릅니다.")
        if rules["preserve_newline_count"] and (src.count("\n"), src.count("\r")) != (dst.count("\n"), dst.count("\r")):
            report("NEWLINE_MISMATCH", u, "개행 개수가 다릅니다.")
        if rules["max_chars"] is not None and len(dst) > rules["max_chars"]:
            report("LENGTH_EXCEEDED", u, f"코드포인트 제한 {rules['max_chars']}자를 초과했습니다. 픽셀 폭 검사는 별도입니다.")
        applicable = [t for t in bundle["canonical"]["glossary"] if scope_matches(t["scope"], u)
                      and any(form in src for form in t["source_forms"])]
        exact = [t for t in applicable if t["enforcement"] == "exact" and src in t["source_forms"]]
        if len({t["target"] for t in exact}) > 1:
            report("CANONICAL_CONFLICT", u, "동일 문맥에 서로 다른 강제 번역이 적용됩니다.")
        for term in exact:
            if dst != term["target"]:
                report("TERM_EXACT_MISMATCH", u, f"{term['id']}: 정확히 '{term['target']}'이어야 합니다.")
        for term in applicable:
            for forbidden in term.get("forbidden_targets", []):
                if forbidden in dst:
                    report("FORBIDDEN_TERM", u, f"{term['id']}: 금지 표현 '{forbidden}'")
        if src == dst and src.strip():
            report("UNCHANGED_SOURCE", u, "원문과 같습니다. 고유명사 등 의도된 보존인지 확인하십시오.", True)
        if dst != unicodedata.normalize("NFC", dst):
            report("NON_NFC", u, "유니코드 NFC 정규화 여부를 확인하십시오. 자동으로 변경하지 않습니다.", True)
    return {"checks_version": CHECKS_VERSION, "passed": not errors, "errors": errors, "warnings": warnings,
            "not_checked": ["semantic_accuracy", "speaker_voice", "font_rendering", "pixel_width", "game_execution"]}
