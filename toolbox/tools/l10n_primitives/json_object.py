"""UTF-8 object-string adapter extracted from conversation kit v0.1.0.

The JsonDocument implementation is unchanged; no installer, workflow, or state
store is included. See docs/PROVENANCE.ko.md.
"""
from __future__ import annotations
import hashlib
import json
from typing import Any

MAX_BYTES = 16 * 1024 * 1024


class PatchError(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(ok: bool, message: str) -> None:
    if not ok:
        raise PatchError(message)


def pairs_unique(pairs: list) -> dict:
    obj: dict = {}
    for k, v in pairs:
        check(k not in obj, f"Duplicate JSON key: {k}")
        obj[k] = v
    return obj


def strict_json(raw: bytes | str) -> Any:
    check(len(raw) <= MAX_BYTES, "JSON is larger than 16 MiB")
    try:
        obj = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw,
                         object_pairs_hook=pairs_unique,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return obj
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PatchError(f"Invalid UTF-8 JSON: {exc}") from exc


def pointer_child(parent: str, key: str) -> str:
    return parent + "/" + key.replace("~", "~0").replace("/", "~1")


class JsonDocument:
    """Locate string VALUE tokens, retaining every other byte of the document.

    Parsing is intentionally narrow: object root, UTF-8 (+ optional BOM), no
    duplicate keys, no non-finite numbers, depth <= 128. Arrays are parsed for
    correctness but their contents are never offered for translation.
    """
    def __init__(self, raw: bytes):
        self.raw = raw
        self.value = strict_json(raw)
        check(isinstance(self.value, dict), "Only a JSON object root is supported")
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        self.text = raw.decode("utf-8-sig")
        self.spans: dict[str, tuple[int, int, str]] = {}
        self.skipped_arrays: list[str] = []
        self.decoder = json.JSONDecoder()
        end = self._walk(self._space(0), "", False, 0)
        check(self._space(end) == len(self.text), "Trailing JSON content")

    def _space(self, i: int) -> int:
        while i < len(self.text) and self.text[i] in " \r\n\t":
            i += 1
        return i

    def _walk(self, i: int, pointer: str, in_array: bool, depth: int) -> int:
        check(depth <= 128, "JSON nesting exceeds 128")
        i = self._space(i)
        c = self.text[i]
        if c == '"':
            value, end = self.decoder.raw_decode(self.text, i)
            if not in_array:
                self.spans[pointer] = (i, end, value)
            return end
        if c == "{":
            i = self._space(i + 1)
            if self.text[i] == "}":
                return i + 1
            while True:
                key, i = self.decoder.raw_decode(self.text, i)
                i = self._space(i)
                check(self.text[i] == ":", "Expected colon")
                i = self._space(self._walk(i + 1, pointer_child(pointer, key), in_array, depth + 1))
                if self.text[i] == "}":
                    return i + 1
                check(self.text[i] == ",", "Expected comma")
                i = self._space(i + 1)
        if c == "[":
            if not in_array:
                self.skipped_arrays.append(pointer)
            i, index = self._space(i + 1), 0
            if self.text[i] == "]":
                return i + 1
            while True:
                i = self._space(self._walk(i, pointer_child(pointer, str(index)), True, depth + 1))
                if self.text[i] == "]":
                    return i + 1
                check(self.text[i] == ",", "Expected comma")
                i, index = self._space(i + 1), index + 1
        _, end = self.decoder.raw_decode(self.text, i)
        return end

    def apply(self, changes: dict[str, str]) -> bytes:
        replacements: list[tuple[int, int, str]] = []
        for ptr, target in changes.items():
            check(ptr in self.spans, f"Not a translatable object-string pointer: {ptr}")
            check(isinstance(target, str), f"Target is not a string: {ptr}")
            start, end, source = self.spans[ptr]
            if target == source:
                continue  # Preserve existing escape spelling on a no-op.
            try:
                token = json.dumps(target, ensure_ascii=False)
                token.encode("utf-8")
            except UnicodeError as exc:
                raise PatchError("Invalid Unicode target") from exc
            replacements.append((start, end, token))
        text = self.text
        for start, end, token in sorted(replacements, reverse=True):
            text = text[:start] + token + text[end:]
        result = (b"\xef\xbb\xbf" if self.bom else b"") + text.encode("utf-8")
        after = JsonDocument(result)
        check(after.spans.keys() == self.spans.keys(), "Unexpected structural mutation")
        for ptr, (_, _, value) in self.spans.items():
            check(after.spans[ptr][2] == changes.get(ptr, value), f"Unexpected value mutation: {ptr}")
        return result


