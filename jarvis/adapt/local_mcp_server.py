"""Local MCP stdio server for handshake tests. Official JSON-RPC methods."""

from __future__ import annotations

import json
import sys


def reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            reply(msg_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jarvis-local", "version": "0.1.0"},
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            reply(msg_id, {"tools": [
                {"name": "ping", "description": "local ping", "inputSchema": {"type": "object"}},
                {"name": "echo", "description": "echo text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
                {"name": "write_note", "description": "protected write", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
            ]})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "ping":
                reply(msg_id, {"content": [{"type": "text", "text": "pong"}]})
            elif name == "echo":
                reply(msg_id, {"content": [{"type": "text", "text": str(args.get("text", ""))}]})
            elif name == "write_note":
                reply(msg_id, {"content": [{"type": "text", "text": "wrote"}]})
            else:
                reply(msg_id, {"content": [{"type": "text", "text": "unknown"}], "isError": True})
        elif msg_id is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "method not found"}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
