"""Real local MCP handshake. External servers stay NOT_CONNECTED."""

from __future__ import annotations

from jarvis.adapt.mcp_catalog import MCPConfig
from jarvis.adapt.mcp_runtime import MCPRuntime


def test_local_handshake_and_tool():
    runtime = MCPRuntime(MCPConfig("local", enabled=True))
    try:
        status = runtime.start_local()
        assert status["status"] == "CONNECTED"
        assert "ping" in status["tools"]
        out = runtime.call("ping")
        assert out["status"] == "EXECUTED"
        assert "pong" in str(out["result"])
    finally:
        runtime.stop()


def test_external_not_faked():
    runtime = MCPRuntime(MCPConfig("github", enabled=True))
    assert runtime.start_local()["status"] == "BLOCKED"
    assert runtime.connected is False
