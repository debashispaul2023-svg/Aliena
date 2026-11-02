"""Parse agent-reach doctor JSON into a health summary."""

from __future__ import annotations

from typing import Any


def parse_doctor(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") or {}
    channels = []
    for ch in result.get("channels") or []:
        channels.append(
            {
                "channel": ch.get("channel"),
                "status": ch.get("status"),
                "level": ch.get("level"),
                "problems": list(ch.get("problems") or []),
            }
        )
    return {
        "ok": bool(payload.get("ok")),
        "version": result.get("version"),
        "channels": channels,
        "available": [c["channel"] for c in channels if c["status"] not in {"not_added", "needs_setup"}],
    }
