"""Multi-MCP workflow using verified servers only."""

from __future__ import annotations

import json
import select
import subprocess
import sys
import tempfile
from pathlib import Path

from jarvis.adapt.mcp_ssrf import is_blocked_url
from jarvis.adapt.skills_adapt import SkillDraft


def _rpc(proc, method, params, msg_id, timeout=25):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}) + "\n")
    proc.stdin.flush()
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        return None
    return json.loads(proc.stdout.readline())


def _session(cmd):
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    init = _rpc(proc, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "jarvis", "version": "1"}}, 1)
    if not init or "result" not in init:
        proc.terminate()
        raise RuntimeError("handshake_failed")
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    return proc, init["result"]


def research(url: str = "https://example.com") -> dict:
    blocked = is_blocked_url(url)
    if blocked:
        return {"ok": False, "status": "BLOCKED", "reason": blocked, "untrusted": True}

    root = Path(tempfile.mkdtemp(prefix="jarvis-mcp-"))
    seq, _ = _session(["npx", "-y", "@modelcontextprotocol/server-sequential-thinking"])
    fetch, _ = _session([sys.executable, "-m", "mcp_server_fetch"])
    fs, _ = _session(["npx", "-y", "@modelcontextprotocol/server-filesystem", str(root)])
    mem, _ = _session(["npx", "-y", "@modelcontextprotocol/server-memory"])
    try:
        plan = _rpc(seq, "tools/call", {"name": "sequentialthinking", "arguments": {"thought": "plan research", "nextThoughtNeeded": False, "thoughtNumber": 1, "totalThoughts": 1}}, 2)
        page = _rpc(fetch, "tools/call", {"name": "fetch", "arguments": {"url": url, "max_length": 800}}, 2)
        graph = _rpc(mem, "tools/call", {"name": "read_graph", "arguments": {}}, 2)
        text = page["result"]["content"][0]["text"][:400] if page else ""
        report = root / "report.txt"
        report.write_text(text)
        listed = _rpc(fs, "tools/call", {"name": "list_directory", "arguments": {"path": str(root)}}, 2)
        draft = SkillDraft(name="research-flow", body="plan, fetch, save", tested=False, approved=False)
        return {
            "ok": True,
            "status": "EXECUTED",
            "untrusted": True,
            "plan": bool(plan),
            "page": text[:120],
            "memory": bool(graph),
            "saved": report.exists(),
            "listed": "report.txt" in str(listed),
            "skill_active": draft.activate(),
        }
    finally:
        for proc in (seq, fetch, fs, mem):
            proc.terminate()
