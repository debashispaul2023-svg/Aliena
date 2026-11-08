"""Mock adapter for unit tests only. Does not claim real desktop execution."""

from __future__ import annotations

from typing import Any

from jarvis.desktop.platforms.base import PlatformAdapter


class MockAdapter(PlatformAdapter):
    name = "mock"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.cancelled = False

    def available(self) -> bool:
        return True

    def cancel(self) -> None:
        self.cancelled = True

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.cancelled:
            return {"ok": False, "status": "CANCELLED", "executed": False, "mock": True}
        self.calls.append((action, dict(params)))
        return {
            "ok": True,
            "status": "MOCK_OK",
            "action": action,
            "executed": False,  # explicit: mock is not real execution
            "mock": True,
        }
