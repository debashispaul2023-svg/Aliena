"""Agent Reach integration tests. No live submission."""

from __future__ import annotations

from jarvis.integrations.agent_reach.client import research, run_action
from jarvis.integrations.agent_reach.health import parse_doctor
from jarvis.integrations.agent_reach.security import SecurityError, redact, validate_url
import pytest


def test_doctor_parse():
    health = parse_doctor(
        {
            "ok": True,
            "result": {
                "version": "1.6.1",
                "channels": [
                    {"channel": "web", "status": "unverified", "level": "default"},
                    {"channel": "twitter", "status": "not_added", "level": "experimental"},
                ],
            },
        }
    )
    assert health["version"] == "1.6.1"
    assert "web" in health["available"]
    assert "twitter" not in health["available"]


def test_reject_unsafe_url():
    with pytest.raises(SecurityError):
        validate_url("http://127.0.0.1/secret")
    with pytest.raises(SecurityError):
        validate_url("file:///etc/passwd")


def test_redact():
    assert "REDACTED" in redact("api_key=supersecret")


def test_allowlist():
    with pytest.raises(SecurityError):
        run_action("shell")


def _public_addrinfo(host, port, *args, **kwargs):
    return [(None, None, None, None, ("93.184.216.34", 0))]


def test_research_marks_untrusted(monkeypatch):
    def fake_run(cmd):
        return {"ok": True, "status": "OK", "result": {"items": [{"title": "Ex", "url": "https://example.com", "text": "hi"}]}}
    monkeypatch.setattr("jarvis.integrations.agent_reach.client._run", fake_run)
    monkeypatch.setattr("jarvis.integrations.agent_reach.client.find_cli", lambda: "/bin/agent-reach")
    monkeypatch.setattr("jarvis.integrations.agent_reach.security.socket.getaddrinfo", _public_addrinfo)
    result = research("https://example.com/jobs")
    assert result["untrusted"] is True
    assert result["items"]


def test_dns_failure_fails_closed(monkeypatch):
    import socket
    def boom(host, port, *args, **kwargs):
        raise socket.gaierror("no network")
    monkeypatch.setattr("jarvis.integrations.agent_reach.security.socket.getaddrinfo", boom)
    with pytest.raises(SecurityError):
        validate_url("https://example.com/")


def test_private_dns_rejected(monkeypatch):
    def private(host, port, *args, **kwargs):
        return [(None, None, None, None, ("10.1.2.3", 0))]
    monkeypatch.setattr("jarvis.integrations.agent_reach.security.socket.getaddrinfo", private)
    with pytest.raises(SecurityError):
        validate_url("https://example.com/")


def test_public_dns_allowed(monkeypatch):
    monkeypatch.setattr("jarvis.integrations.agent_reach.security.socket.getaddrinfo", _public_addrinfo)
    assert validate_url("https://example.com/") == "https://example.com/"
