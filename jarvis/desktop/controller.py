"""Desktop controller: routes validated, approved actions to a platform adapter."""

from __future__ import annotations

from typing import Any

from jarvis.desktop.audit import AuditLogger
from jarvis.desktop.capabilities import CapabilityReport, detect_environment
from jarvis.desktop.platforms.base import PlatformAdapter
from jarvis.desktop.platforms.mock import MockAdapter
from jarvis.desktop.platforms.unsupported import UnsupportedAdapter


class DesktopController:
    def __init__(self, adapter: PlatformAdapter | None = None, audit: AuditLogger | None = None) -> None:
        self.report = detect_environment()
        if adapter is not None:
            self.adapter = adapter
        elif self.report.is_desktop:
            # Real desktop driver is not verified in this runtime.
            self.adapter = UnsupportedAdapter()
        else:
            self.adapter = UnsupportedAdapter()
        self.audit = audit or AuditLogger()
        self._cancelled = False

    def capabilities(self) -> CapabilityReport:
        return self.report

    def cancel(self) -> dict[str, Any]:
        self._cancelled = True
        if hasattr(self.adapter, "cancel"):
            self.adapter.cancel()  # type: ignore[attr-defined]
        self.audit.record("cancel", "OK")
        return {"ok": True, "status": "CANCELLED"}

    def execute(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if self._cancelled:
            self.audit.record(action, "CANCELLED")
            return {"ok": False, "status": "CANCELLED", "executed": False}
        if action in {"detect_environment", "list_capabilities"}:
            data = {
                "platform": self.report.platform,
                "is_desktop": self.report.is_desktop,
                "status": self.report.status,
                "capabilities": self.report.capabilities,
            }
            self.audit.record(action, "OK")
            return {"ok": True, "status": "OK", "data": data, "executed": False}
        result = self.adapter.execute(action, params)
        self.audit.record(action, result.get("status", "UNKNOWN"), detail=str(result.get("reason", "")))
        return result


def build_test_controller() -> DesktopController:
    """Controller wired to MockAdapter for unit tests only."""
    return DesktopController(adapter=MockAdapter())
