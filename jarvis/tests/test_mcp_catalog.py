"""MCP catalog tests. No live external servers."""

from __future__ import annotations

from jarvis.adapt.mcp_catalog import CATALOG, MCPClient, MCPConfig


def test_postgres_archived_blocked():
    client = MCPClient(MCPConfig("postgres", enabled=True))
    assert client.connect(handshake_ok=True)["status"] == "BLOCKED"
    assert "crystaldba/postgres-mcp" in CATALOG["postgres"]["alternative"]


def test_filesystem_needs_root():
    client = MCPClient(MCPConfig("filesystem", enabled=True))
    assert client.connect()["reason"] == "filesystem_root_required"


def test_disabled_not_connected():
    client = MCPClient(MCPConfig("github"))
    assert client.status()["status"] == "DISABLED"


def test_mock_handshake_and_approval(tmp_path):
    client = MCPClient(MCPConfig("filesystem", enabled=True, roots=[str(tmp_path)]))
    assert client.connect(handshake_ok=True)["status"] == "CONNECTED"
    assert client.call("write_file")["status"] == "APPROVAL_REQUIRED"
    assert client.call("read_file", {"path": str(tmp_path / "a.txt")})["status"] == "MOCKED"
    outside = client.call("read_file", {"path": "/etc/passwd"})
    assert outside["status"] == "PATH_BLOCKED"


def test_no_fake_live_without_handshake():
    client = MCPClient(MCPConfig("fetch", enabled=True))
    client.connect(handshake_ok=False)
    assert client.status()["status"] == "NOT_CONNECTED"
