"""Conflict detection for agent outputs."""

from __future__ import annotations


def detect_conflict(claims: list[dict]) -> dict | None:
    texts = [str(c.get("claim", "")).lower() for c in claims]
    if any("yes" in t for t in texts) and any("no" in t for t in texts):
        return {
            "status": "CONFLICT",
            "claims": claims,
            "action": "escalate",
        }
    return None
