"""Unsupported environment adapter. Always fails closed."""

from __future__ import annotations

from typing import Any

from jarvis.desktop.platforms.base import PlatformAdapter


class UnsupportedAdapter(PlatformAdapter):
    name = "unsupported"

    def available(self) -> bool:
        return False

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "UNSUPPORTED",
            "reason": "desktop environment unavailable",
            "action": action,
            "executed": False,
        }
