"""Input sanitising + per-context escapers for composers. Specs are untrusted data."""

from __future__ import annotations

import html
import json
import re
from typing import Any

MAX_TEXT = 300


class SpecError(ValueError):
    pass


def clean_text(value: Any, field: str, *, maxlen: int = MAX_TEXT, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SpecError(f"{field} must be a string")
    v = re.sub(r"\s+", " ", value).strip()
    if not v and not allow_empty:
        raise SpecError(f"{field} is required")
    if len(v) > maxlen:
        raise SpecError(f"{field} too long (max {maxlen})")
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise SpecError(f"{field} contains control characters")
    return v


def clean_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.match(r"^[a-z][a-z0-9_]{0,30}$", value):
        raise SpecError(f"{field} must match [a-z][a-z0-9_]{{0,30}}")
    if value in _PY_RESERVED:
        raise SpecError(f"{field} is a reserved word")
    return value


def clean_color(value: Any, field: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not re.match(r"^#[0-9a-fA-F]{6}$", value):
        raise SpecError(f"{field} must be a #rrggbb colour")
    return value.lower()


def clean_list(value: Any, field: str, *, max_items: int, min_items: int = 0) -> list:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise SpecError(f"{field} must be a list")
    if not (min_items <= len(value) <= max_items):
        raise SpecError(f"{field} must have {min_items}..{max_items} items")
    return value


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "item"


def pyname(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s if s and s[0].isalpha() else "app_" + s


def reject_unknown(spec: dict, allowed: set, where: str = "spec") -> None:
    extra = set(spec) - allowed
    if extra:
        raise SpecError(f"unknown keys in {where}: {sorted(extra)}")


# ---- context escapers ----
def h(text: str) -> str:
    return html.escape(text, quote=True)


def js(value: Any) -> str:
    """JSON/JS literal safe inside <script> and JS source."""
    return (json.dumps(value, ensure_ascii=True)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def py(value: Any) -> str:
    return repr(value)


_PY_RESERVED = {"class", "def", "return", "import", "from", "global", "lambda", "pass", "del", "yield", "assert",
                "async", "await", "with", "while", "for", "if", "else", "elif", "try", "except", "finally",
                "raise", "in", "is", "not", "and", "or", "none", "true", "false", "id", "type", "list",
                "dict", "str", "int", "float", "bool", "object", "set", "map", "filter", "print", "input"}
