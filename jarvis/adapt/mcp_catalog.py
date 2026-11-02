"""MCP server catalog and fail-closed client.

Live sessions are NOT_CONNECTED until a real stdio/HTTP handshake succeeds.
Archived servers are registered but disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Verified 2026-11-03. Do not mark these as connected.
CATALOG = {
    "github": {
        "repo": "https://github.com/github/github-mcp-server",
        "status": "official",
        "transport": "stdio",
        "env": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "allow": ["get_file_contents", "search_repositories", "list_commits"],
        "write_tools": ["create_or_update_file", "push_files"],
    },
    "filesystem": {
        "repo": "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        "status": "official",
        "transport": "stdio",
        "env": [],
        "allow": ["read_file", "list_directory", "search_files"],
        "write_tools": ["write_file", "move_file"],
        "requires_root": True,
    },
    "fetch": {
        "repo": "https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
        "status": "official",
        "transport": "stdio",
        "env": [],
        "allow": ["fetch"],
        "write_tools": [],
    },
    "playwright": {
        "repo": "https://github.com/microsoft/playwright-mcp",
        "status": "official",
        "transport": "stdio",
        "env": [],
        "allow": ["browser_navigate", "browser_snapshot"],
        "write_tools": ["browser_click", "browser_type"],
    },
    "postgres": {
        "repo": "https://github.com/modelcontextprotocol/servers-archived/tree/main/src/postgres",
        "status": "ARCHIVED_UNSAFE",
        "alternative": "https://github.com/crystaldba/postgres-mcp",
        "transport": "stdio",
        "env": ["POSTGRES_URL"],
        "allow": [],
        "write_tools": ["query"],
        "note": "Reference server archived May 2025. Known read-only bypass. Do not enable.",
    },
    "sequential": {
        "repo": "https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
        "status": "official",
        "transport": "stdio",
        "env": [],
        "allow": ["sequentialthinking"],
        "write_tools": [],
    },
    "memory": {
        "repo": "https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
        "status": "official",
        "transport": "stdio",
        "env": [],
        "allow": ["read_graph", "search_nodes"],
        "write_tools": ["create_entities"],
    },
    "docker": {
        "repo": "https://github.com/QuantGeekDev/docker-mcp",
        "status": "community",
        "transport": "stdio",
        "env": [],
        "allow": ["list_containers"],
        "write_tools": ["run_container"],
        "privileged": False,
        "note": "No privileged containers. Prefer Docker Desktop MCP toolkit if available.",
    },
}


@dataclass
class MCPConfig:
    name: str
    enabled: bool = False
    roots: list[str] = field(default_factory=list)
    timeout_s: float = 15.0
    approved_writes: set[str] = field(default_factory=set)


class MCPClient:
    def __init__(self, config: MCPConfig):
        if config.name not in CATALOG:
            raise KeyError(config.name)
        self.config = config
        self.meta = CATALOG[config.name]
        self.connected = False

    def status(self) -> dict:
        if self.meta["status"] == "ARCHIVED_UNSAFE":
            return {"ok": False, "status": "BLOCKED", "reason": "archived_unsafe"}
        if not self.config.enabled:
            return {"ok": False, "status": "DISABLED"}
        if not self.connected:
            return {"ok": False, "status": "NOT_CONNECTED"}
        return {"ok": True, "status": "CONNECTED"}

    def connect(self, *, handshake_ok: bool = False) -> dict:
        """handshake_ok is only True in a real test that completed initialize."""
        if self.meta["status"] == "ARCHIVED_UNSAFE":
            return {"ok": False, "status": "BLOCKED", "reason": "archived_unsafe"}
        if not self.config.enabled:
            return {"ok": False, "status": "DISABLED"}
        if self.meta.get("requires_root") and not self.config.roots:
            return {"ok": False, "status": "BLOCKED", "reason": "filesystem_root_required"}
        self.connected = bool(handshake_ok)
        return self.status()

    def call(self, tool: str, args: Optional[dict] = None, *, approved: bool = False) -> dict:
        state = self.status()
        if state["status"] != "CONNECTED":
            return {"ok": False, "status": state["status"], "tool": tool}
        if tool in self.meta.get("write_tools", []) and not approved:
            return {"ok": False, "status": "APPROVAL_REQUIRED", "tool": tool}
        if tool not in self.meta.get("allow", []) and tool not in self.meta.get("write_tools", []):
            return {"ok": False, "status": "NOT_ALLOWLISTED", "tool": tool}
        if self.meta.get("requires_root") and args and "path" in args:
            if not _inside(args["path"], self.config.roots):
                return {"ok": False, "status": "PATH_BLOCKED", "tool": tool}
        return {"ok": True, "status": "MOCKED", "tool": tool, "note": "local mock only"}


def _inside(path: str, roots: list[str]) -> bool:
    target = Path(path).resolve()
    for root in roots:
        try:
            target.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False
