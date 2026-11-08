"""Compatibility facade over the Feature 8 Desktop Automation Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.desktop.engine import DesktopAutomationEngine


@dataclass
class DesktopAction:
    name: str
    approved: bool = False
    params: dict[str, Any] | None = None


class DesktopAutomation:
    """Legacy-friendly wrapper. Does not claim verified desktop drivers."""

    def __init__(self, engine: DesktopAutomationEngine | None = None) -> None:
        self.engine = engine or DesktopAutomationEngine()

    def available(self) -> bool:
        report = self.engine.controller.capabilities()
        return report.is_desktop

    def run(self, action: DesktopAction) -> dict[str, Any]:
        if not action.approved:
            return {"ok": False, "status": "approval_required", "executed": False}
        self.engine.grant(action.name)
        self.engine.approve(action.name)
        return self.engine.run(action.name, action.params or {})
