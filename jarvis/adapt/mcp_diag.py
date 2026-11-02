"""MCP diagnostics. CONNECTED only after a real handshake."""

from __future__ import annotations

import json
import select
import subprocess
from typing import Optional


def probe(command: list[str], timeout: float = 20.0) -> dict:
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        return {"status": "NOT_CONNECTED", "error": str(exc)}

    def rpc(method: str, params: dict, msg_id: int) -> Optional[dict]:
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        if not ready:
            return None
        return json.loads(proc.stdout.readline())

    try:
        init = rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "jarvis", "version": "1"}}, 1)
        if not init or "result" not in init:
            return {"status": "NOT_CONNECTED", "error": "handshake_failed"}
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        tools = rpc("tools/list", {}, 2)
        names = [t["name"] for t in (tools or {}).get("result", {}).get("tools", [])]
        return {"status": "CONNECTED", "server": init["result"].get("serverInfo"), "tools": names}
    except Exception as exc:
        return {"status": "NOT_CONNECTED", "error": str(exc)}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()


def detect_runtime() -> dict:
    import shutil
    return {
        "node": shutil.which("node") is not None,
        "npx": shutil.which("npx") is not None,
        "python": shutil.which("python3") is not None,
        "docker": shutil.which("docker") is not None,
        "uvx": shutil.which("uvx") is not None,
    }
