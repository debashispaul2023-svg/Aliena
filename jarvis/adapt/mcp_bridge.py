"""Orchestrator bridge to MCP runtime. Local only unless a real session exists."""

from __future__ import annotations

from typing import Any, Optional

from jarvis.adapt.approval_center import ApprovalCenter
from jarvis.adapt.mcp_catalog import MCPConfig
from jarvis.adapt.mcp_runtime import MCPRuntime
from jarvis.adapt.skills_adapt import SkillDraft

PROTECTED = {"write_note"}


class MCPBridge:
    def __init__(self, approvals: Optional[ApprovalCenter] = None):
        self.approvals = approvals or ApprovalCenter()
        self.runtime: Optional[MCPRuntime] = None
        self.audit: list[dict] = []

    def connect_local(self) -> dict:
        self.runtime = MCPRuntime(MCPConfig("local", enabled=True))
        status = self.runtime.start_local()
        self.audit.append({"event": "connect", **status})
        return status

    def discover(self) -> list[str]:
        if not self.runtime or not self.runtime.connected:
            return []
        return list(self.runtime.tools)

    def select(self, task: str) -> Optional[str]:
        tools = self.discover()
        low = task.lower()
        if "echo" in low and "echo" in tools:
            return "echo"
        if "write" in low and "write_note" in tools:
            return "write_note"
        if "ping" in low and "ping" in tools:
            return "ping"
        return None

    def run_task(self, task: str, args: Optional[dict] = None, *, approved: bool = False) -> dict:
        if not self.runtime or not self.runtime.connected:
            return {"ok": False, "status": "NOT_CONNECTED", "untrusted": True}
        tool = self.select(task)
        if not tool:
            return {"ok": False, "status": "NO_TOOL", "untrusted": True}
        if tool in PROTECTED and not approved:
            key = self.approvals.request(tool, task)
            return {"ok": False, "status": "APPROVAL_REQUIRED", "key": key, "untrusted": True}
        result = self.runtime.call(tool, args or {}, approved=approved)
        result["untrusted"] = True
        self.audit.append({"event": "call", "tool": tool, "status": result.get("status")})
        return result

    def draft_skill(self, name: str, body: str) -> SkillDraft:
        return SkillDraft(name=name, body=body, tested=False, approved=False)

    def close(self) -> None:
        if self.runtime:
            self.runtime.stop()
