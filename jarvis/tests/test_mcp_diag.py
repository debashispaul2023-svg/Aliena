"""Diagnostics and wizard tests. External probes are not run here."""

from __future__ import annotations

from jarvis.adapt.mcp_diag import detect_runtime
from jarvis.adapt.mcp_wizard import wizard


def test_runtime_detects_python():
    info = detect_runtime()
    assert info["python"] is True


def test_wizard_mentions_root_and_token(monkeypatch):
    monkeypatch.delenv("JARVIS_FS_ROOT", raising=False)
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    text = "\n".join(wizard())
    assert "JARVIS_FS_ROOT" in text
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in text
    assert "Do not use /" in text
