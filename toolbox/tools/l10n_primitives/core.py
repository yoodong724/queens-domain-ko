"""Bounded JSON, content hashes, and new-output-only filesystem operations."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

MAX_BYTES = 16 * 1024 * 1024


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def payload(self) -> dict:
        return {"ok": False, "error": self.code, "message": self.message, "details": self.details}


def require(condition: bool, code: str, message: str, details: Any = None) -> None:
    if not condition:
        raise ToolError(code, message, details)


def fields(obj: Any, required: set[str], optional: set[str] | None = None) -> None:
    require(isinstance(obj, dict), "SCHEMA_ERROR", "JSON 객체가 필요합니다.")
    require(required <= set(obj), "SCHEMA_ERROR", "필수 필드가 없습니다.", sorted(required - set(obj)))
    require(set(obj) <= required | (optional or set()), "SCHEMA_ERROR", "알 수 없는 필드입니다.",
            sorted(set(obj) - required - (optional or set())))


def nonempty(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), "SCHEMA_ERROR", f"{name}: 빈 문자열은 허용하지 않습니다.")
    return value


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(obj: Any) -> bytes:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ToolError("INVALID_JSON_VALUE", str(exc)) from exc


def revision(obj: Any) -> str:
    return digest(encoded(obj))


def pretty(obj: Any) -> bytes:
    try:
        raw = (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ToolError("INVALID_JSON_VALUE", str(exc)) from exc
    require(len(raw) <= MAX_BYTES, "OUTPUT_TOO_LARGE", "JSON 출력 한도는 16 MiB입니다.")
    return raw


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY", f"중복 JSON 키: {key}")
        result[key] = value
    return result


def parse_json(raw: bytes) -> Any:
    require(len(raw) <= MAX_BYTES, "INPUT_TOO_LARGE", "JSON 입력 한도는 16 MiB입니다.")
    try:
        obj = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_pairs,
                         parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
        encoded(obj)  # Reject overflowed floats and unpaired Unicode surrogates.
        return obj
    except ToolError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ToolError("INVALID_JSON", str(exc)) from exc


def safe_absolute(path: Path) -> Path:
    """Reject symlinks in existing path components; not an OS security sandbox."""
    # Inspect the lexical path as well: a symlink followed by '..' is not safe.
    lexical = path.absolute()
    for part in (lexical, *lexical.parents):
        require(not part.is_symlink(), "UNSAFE_PATH", f"심볼릭 링크는 지원하지 않습니다: {part}")
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        require(not part.is_symlink(), "UNSAFE_PATH", f"심볼릭 링크는 지원하지 않습니다: {part}")
    return path


def relative_name(name: Any) -> str:
    require(isinstance(name, str) and bool(name) and not any(x in name for x in ("\\", ":", "\x00", "#")),
            "UNSAFE_PATH", f"안전하지 않은 상대 경로: {name!r}")
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    require(all(p not in ("", ".", "..") and not p.endswith((".", " "))
                and p.split(".")[0].upper() not in reserved for p in parts), "UNSAFE_PATH", name)
    return name


def safe_relative(root: Path, name: str) -> Path:
    relative_name(name)
    root = safe_absolute(root)
    path = safe_absolute(root / name)
    require(path.is_relative_to(root), "UNSAFE_PATH", name)
    return path


def bounded_read(path: Path) -> bytes:
    path = safe_absolute(path)
    require(path.is_file(), "FILE_NOT_FOUND", f"파일이 없습니다: {path}")
    require(path.stat().st_size <= MAX_BYTES, "INPUT_TOO_LARGE", str(path))
    with path.open("rb") as f:
        data = f.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "INPUT_TOO_LARGE", str(path))
    return data


def load_json(path: Path) -> Any:
    return parse_json(bounded_read(path))


def ensure_new(path: Path, *, forbidden_roots: tuple[Path, ...] = (), forbidden_files: tuple[Path, ...] = ()) -> Path:
    path = safe_absolute(path)
    require(not path.exists(), "OUTPUT_EXISTS", f"기존 출력은 덮어쓰지 않습니다: {path}")
    for root in forbidden_roots:
        require(not path.is_relative_to(safe_absolute(root)), "OUTPUT_IN_SOURCE", "원본 디렉터리 안에는 출력하지 않습니다.")
    require(path not in {safe_absolute(p) for p in forbidden_files}, "OUTPUT_IS_INPUT", "입력 파일에는 쓰지 않습니다.")
    return path


def write_new_json(path: Path, value: Any) -> None:
    write_new_files({path: pretty(value)})


def write_new_files(values: dict[Path, bytes]) -> None:
    normalized = [ensure_new(p) for p in values]
    require(len(set(normalized)) == len(values), "OUTPUT_COLLISION", "출력 경로가 중복됩니다.")
    # All preflight checks happen before any outputs are created.
    created: list[Path] = []
    try:
        for path, data in zip(normalized, values.values()):
            path.parent.mkdir(parents=True, exist_ok=True)
            safe_absolute(path)
            with path.open("xb") as f:
                created.append(path)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def write_new_tree(root: Path, files: dict[str, bytes]) -> None:
    root = ensure_new(root)
    for name in files:
        safe_relative(root, name)
    root.parent.mkdir(parents=True, exist_ok=True)
    safe_absolute(root)
    root.mkdir()  # Exclusive creation. Never merge into an existing game folder.
    try:
        write_new_files({safe_relative(root, n): data for n, data in files.items()})
    except BaseException:
        shutil.rmtree(root)
        raise
