"""MCP server registry. Fail-closed. Does not connect without explicit enable."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MCPServer:
    name: str
    transport: str
    enabled: bool = False
    allow: list[str] = field(default_factory=list)

    def call(self, tool: str) -> dict:
        if not self.enabled:
            return {"ok": False, "status": "BLOCKED", "reason": "server_disabled"}
        if tool not in self.allow:
            return {"ok": False, "status": "BLOCKED", "reason": "tool_not_allowlisted"}
        return {"ok": False, "status": "NOT_CONNECTED", "reason": "no_live_mcp_session"}
