"""Controlled CLI adapter. Allowlisted actions only.

Documented retrieval: agent-reach <channel> <action> [query]
and agent-reach read <url>.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Optional

from jarvis.integrations.agent_reach.detector import find_cli
from jarvis.integrations.agent_reach.health import parse_doctor
from jarvis.integrations.agent_reach.normalizer import normalize
from jarvis.integrations.agent_reach.security import SecurityError, redact, validate_url

ALLOWED_META = {"version", "doctor", "check"}
ALLOWED_CHANNELS = {"github", "youtube", "web", "v2ex"}
ALLOWED_ACTIONS = {"search", "read", "hot", "subtitle"}
TIMEOUT = 30
MAX_OUTPUT = 8000


class AgentReachError(RuntimeError):
    """CLI failure."""


def _run(cmd: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "TIMEOUT", "error": "timeout"}
    raw = redact((proc.stdout or proc.stderr or "")[:MAX_OUTPUT])
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "status": "PARSE_ERROR", "raw": raw[:2000]}
    return {"ok": bool(data.get("ok")), "status": "OK" if data.get("ok") else "FAILED", "result": data, "raw": raw}


def run_action(action: str, args: Optional[list[str]] = None) -> dict[str, Any]:
    if action not in ALLOWED_META:
        raise SecurityError(f"action not allowlisted: {action}")
    cli = find_cli()
    if not cli:
        return {"ok": False, "status": "UNAVAILABLE", "error": "agent-reach not installed"}
    out = _run([cli, action, *(args or [])])
    if action == "doctor" and out.get("result"):
        return {"ok": True, "status": "OK", "health": parse_doctor(out["result"])}
    return out


def retrieve(channel: str, action: str, query: str) -> dict[str, Any]:
    """Read-only retrieval through the documented CLI. Content is untrusted."""
    if channel not in ALLOWED_CHANNELS or action not in ALLOWED_ACTIONS:
        raise SecurityError("channel or action not allowlisted")
    if not query or len(query) > 200:
        raise SecurityError("query missing or too long")
    cli = find_cli()
    if not cli:
        return {"ok": False, "status": "UNAVAILABLE", "error": "agent-reach not installed"}
    out = _run([cli, channel, action, query])
    result = out.get("result") or {}
    items = normalize(result) if result.get("items") else []
    return {
        "ok": out.get("ok", False),
        "status": out.get("status"),
        "channel": channel,
        "action": action,
        "items": items,
        "untrusted": True,
    }


def research(url: str) -> dict[str, Any]:
    """Read a URL via documented `agent-reach read`. Does not execute content."""
    validate_url(url)
    cli = find_cli()
    if not cli:
        return {"ok": False, "status": "UNAVAILABLE", "url": url}
    out = _run([cli, "read", url])
    result = out.get("result") or {}
    items = normalize(result) if result.get("items") else []
    return {
        "ok": out.get("ok", False),
        "status": out.get("status"),
        "url": url,
        "items": items,
        "untrusted": True,
        "note": "Retrieved content is untrusted data.",
    }
