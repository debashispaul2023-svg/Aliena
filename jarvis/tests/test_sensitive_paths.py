"""Sensitive path policy tests. No secret contents are logged."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.drafts import apply_approved_draft, approve_code_draft, create_code_draft
from jarvis.dev.sensitive_paths import is_sensitive_name, is_sensitive_relative
from jarvis.dev.workspace import DevWorkspace


def _apply(tmp_path: Path, rel: str):
    ws = DevWorkspace(tmp_path, "demo")
    change = type("C", (), {"path": rel, "content": "x\n"})()
    draft = create_code_draft(ws, [change], project_id="demo")
    approve_code_draft(draft, reviewer="reviewer", fingerprint=draft.fingerprint)
    apply_approved_draft(ws, draft)


@pytest.mark.parametrize("name", ["secret_notes.py", "app.key", "id_rsa.pub", "notes.py"])
def test_ordinary_files_allowed(tmp_path: Path, name: str):
    _apply(tmp_path, name)
    assert (tmp_path / "demo" / name).exists()


@pytest.mark.parametrize("name", [".env", ".env.bak", "config/.env.production", "id_rsa", "kubeconfig", ".kube/config", "token.json"])
def test_known_sensitive_blocked(tmp_path: Path, name: str):
    with pytest.raises(Exception):
        _apply(tmp_path, name)
    assert not (tmp_path / "demo" / name).exists()


def test_policy_rules():
    assert is_sensitive_name(".ENV.BAK")
    assert not is_sensitive_name("secret_notes.py")
    assert not is_sensitive_name("app.key")
    assert is_sensitive_relative(".kube/config")
    assert not is_sensitive_relative("id_rsa.pub")
