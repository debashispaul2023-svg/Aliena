"""Orchestrator to MCP bridge tests. Local only."""

from __future__ import annotations

from jarvis.adapt.mcp_bridge import MCPBridge


def test_discover_and_run():
    bridge = MCPBridge()
    try:
        assert bridge.connect_local()["status"] == "CONNECTED"
        assert "echo" in bridge.discover()
        out = bridge.run_task("echo hello", {"text": "hello"})
        assert out["status"] == "EXECUTED"
        assert out["untrusted"] is True
    finally:
        bridge.close()


def test_write_needs_approval():
    bridge = MCPBridge()
    try:
        bridge.connect_local()
        out = bridge.run_task("write note", {"text": "x"})
        assert out["status"] == "APPROVAL_REQUIRED"
        approved = bridge.run_task("write note", {"text": "x"}, approved=True)
        assert approved["status"] == "EXECUTED"
    finally:
        bridge.close()


def test_disconnected():
    bridge = MCPBridge()
    assert bridge.run_task("ping")["status"] == "NOT_CONNECTED"


def test_skill_draft_not_active():
    bridge = MCPBridge()
    draft = bridge.draft_skill("mcp-echo", "echo a string")
    assert draft.activate() is False
