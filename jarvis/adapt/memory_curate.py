"""Memory curation helpers. Does not replace the existing store."""

from __future__ import annotations

from typing import Any


def importance(text: str) -> float:
    score = 0.2
    low = text.lower()
    if any(k in low for k in ("prefer", "always", "never", "project")):
        score += 0.4
    if len(text) > 40:
        score += 0.2
    return min(1.0, score)


def is_duplicate(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def contradicts(a: str, b: str) -> bool:
    pair = (a.lower(), b.lower())
    flags = (("offline", "must use network"), ("no database", "sqlite"))
    return any(x in pair[0] and y in pair[1] or y in pair[0] and x in pair[1] for x, y in flags)


def project_memory(items: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    return [i for i in items if i.get("project_id") == project_id]
