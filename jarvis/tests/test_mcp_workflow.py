"""SSRF and workflow tests. Workflow hits real local servers."""

from __future__ import annotations

from jarvis.adapt.mcp_ssrf import is_blocked_url
from jarvis.adapt.mcp_workflow import research


def test_ssrf_blocks_private():
    assert is_blocked_url("http://127.0.0.1") == "blocked_ip"
    assert is_blocked_url("http://169.254.169.254") in {"metadata", "blocked_ip"}
    assert is_blocked_url("https://example.com") is None


def test_research_workflow():
    out = research("https://example.com")
    assert out["status"] == "EXECUTED"
    assert out["untrusted"] is True
    assert out["saved"] is True
    assert out["skill_active"] is False
