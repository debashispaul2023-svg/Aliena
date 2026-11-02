"""Normalize Agent Reach items as untrusted data. Never execute them."""

from __future__ import annotations

from typing import Any


def normalize(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items") or []
    out = []
    for item in items:
        out.append(
            {
                "source": payload.get("channel"),
                "backend": payload.get("backend"),
                "title": str(item.get("title") or "")[:200],
                "url": str(item.get("url") or ""),
                "text": str(item.get("text") or "")[:500],
                "untrusted": True,
            }
        )
    return out
