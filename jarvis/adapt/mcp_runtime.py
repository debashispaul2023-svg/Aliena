"""MCP stdio runtime. Handshake must succeed before CONNECTED."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from jarvis.adapt.mcp_catalog import CATALOG, MCPConfig


class MCPRuntime:
    def __init__(self, config: MCPConfig):
        self.config = config
        self.proc: Optional[subprocess.Popen] = None
        self.connected = False
        self.tools: list[str] = []
        self.last_error: Optional[str] = None
        self.executed: list[str] = []

    def start_local(self) -> dict:
        if self.config.name != "local":
            return {"ok": False, "status": "BLOCKED", "reason": "only_local_server_in_this_runtime"}
        script = Path(__file__).with_name("local_mcp_server.py")
        self.proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        init = self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "jarvis", "version": "1"}})
        if not init or "protocolVersion" not in init:
            self.last_error = "handshake_failed"
            self.stop()
            return {"ok": False, "status": "NOT_CONNECTED", "error": self.last_error}
        self._notify("notifications/initialized")
        listed = self._rpc("tools/list", {})
        self.tools = [t["name"] for t in (listed or {}).get("tools", [])]
        self.connected = True
        return {"ok": True, "status": "CONNECTED", "tools": self.tools}

    def call(self, tool: str, args: Optional[dict] = None, *, approved: bool = False) -> dict:
        if not self.connected:
            return {"ok": False, "status": "NOT_CONNECTED"}
        meta = CATALOG.get(self.config.name, {"allow": ["ping"], "write_tools": []})
        if tool in meta.get("write_tools", []) and not approved:
            return {"ok": False, "status": "APPROVAL_REQUIRED"}
        result = self._rpc("tools/call", {"name": tool, "arguments": args or {}})
        if not result:
            return {"ok": False, "status": "CALL_FAILED", "error": self.last_error}
        self.executed.append(tool)
        return {"ok": True, "status": "EXECUTED", "result": result}

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.connected = False

    def _rpc(self, method: str, params: dict) -> Optional[dict]:
        if not self.proc or not self.proc.stdin or not self.proc.stdout:
            return None
        try:
            self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
            data = json.loads(line)
            if "error" in data:
                self.last_error = str(data["error"])
                return None
            return data.get("result")
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def _notify(self, method: str) -> None:
        if self.proc and self.proc.stdin:
            self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
            self.proc.stdin.flush()
