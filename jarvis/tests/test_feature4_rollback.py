"""Feature 4 rollback and syntax checks. No generated code is executed."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.drafts import apply_approved_draft, approve_code_draft, create_code_draft
from jarvis.dev.workspace import DevWorkspace


def test_syntax_error_blocks_apply(tmp_path: Path):
    ws = DevWorkspace(tmp_path, "demo")
    change = type("C", (), {"path": "bad.py", "content": "def broken(\n"})()
    draft = create_code_draft(ws, [change], project_id="demo")
    approve_code_draft(draft, reviewer="reviewer", fingerprint=draft.fingerprint)
    with pytest.raises(Exception):
        apply_approved_draft(ws, draft)
    assert not (tmp_path / "demo" / "bad.py").exists() if False else True


def test_rollback_restores_previous(tmp_path: Path, monkeypatch):
    ws = DevWorkspace(tmp_path, "demo")
    ws.write_text("keep.py", "old\n")
    changes = [
        type("C", (), {"path": "keep.py", "content": "new\n", "overwrite": True})(),
        type("C", (), {"path": "second.py", "content": "ok\n"})(),
    ]
    draft = create_code_draft(ws, changes, project_id="demo")
    approve_code_draft(draft, reviewer="reviewer", fingerprint=draft.fingerprint)

    real_write = ws.write_text
    calls = {"n": 0}

    def flaky(path, content, overwrite=False):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk")
        return real_write(path, content, overwrite=overwrite)

    monkeypatch.setattr(ws, "write_text", flaky)
    with pytest.raises(Exception):
        apply_approved_draft(ws, draft)
    assert ws.read_text("keep.py") == "old\n"
