"""Per-project Creator memory, stored inside the project's own control area (never mixed across projects,
never touching Aliena's global memory or SQLite databases)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.core.redaction import redact_secrets
from jarvis.creator.workspace_manager import CreatorWorkspaceError, CreatorWorkspaceManager

KINDS = ("requirements", "stack", "decision", "phase", "test_result", "known_error", "approved_change", "delivery_status")
MAX_ENTRIES = 500
MAX_ENTRY_BYTES = 8192


def _redact(v: Any) -> Any:
    if isinstance(v, str):
        return redact_secrets(v)
    if isinstance(v, dict):
        return {str(k): _redact(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_redact(x) for x in v]
    return v


class CreatorProjectMemory:
    def __init__(self, ws: CreatorWorkspaceManager, pid: str) -> None:
        self.ws, self.pid = ws, pid
        ws.metadata(pid)  # validates the project exists

    def _load(self) -> dict[str, Any]:
        try:
            return self.ws.load_control_record(self.pid, "memory", "main")
        except CreatorWorkspaceError:
            return {"project_id": self.pid, "entries": []}

    def add(self, kind: str, data: Any) -> dict[str, Any]:
        if kind not in KINDS:
            raise CreatorWorkspaceError(f"unknown memory kind: {kind}")
        entry = {"kind": kind, "data": _redact(data), "at": datetime.now(timezone.utc).isoformat()}
        if len(json.dumps(entry, default=str)) > MAX_ENTRY_BYTES:
            raise CreatorWorkspaceError("memory entry too large")
        mem = self._load()
        mem["entries"] = (mem["entries"] + [entry])[-MAX_ENTRIES:]
        self.ws.save_control_record(self.pid, "memory", "main", json.loads(json.dumps(mem, default=str)))
        return entry

    def entries(self, kind: Optional[str] = None) -> list[dict[str, Any]]:
        return [e for e in self._load()["entries"] if kind in (None, e["kind"])]

    def latest(self, kind: str) -> Optional[Any]:
        found = self.entries(kind)
        return found[-1]["data"] if found else None
