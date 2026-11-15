"""Feature 4 development engine drafts. Execution remains blocked."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.drafts import apply_approved_draft, approve_code_draft, create_code_draft
from jarvis.dev.execution_backend import STATUS_BLOCKED
from jarvis.dev.workspace import DevWorkspace


def test_draft_diff_requires_approval(tmp_path: Path):
    ws = DevWorkspace(tmp_path, "demo")
    ws.write_text("notes.py", "old\n")
    change = type("C", (), {"path": "notes.py", "content": "new\n", "overwrite": True})()
    draft = create_code_draft(ws, [change], project_id="demo")
    assert "notes.py" in draft.files[0].unified_diff
    with pytest.raises(Exception):
        apply_approved_draft(ws, draft)
    approve_code_draft(draft, reviewer="reviewer", fingerprint=draft.fingerprint)
    written = apply_approved_draft(ws, draft)
    assert written == ["notes.py"]


def test_phase6f_blocked():
    status = Path("jarvis/dev/phase6_status.json").read_text()
    assert STATUS_BLOCKED in status or '"execution": "BLOCKED"' in status


def test_path_escape_blocked(tmp_path: Path):
    ws = DevWorkspace(tmp_path, "demo")
    change = type("C", (), {"path": "../escape.txt", "content": "nope\n"})()
    with pytest.raises(Exception):
        create_code_draft(ws, [change], project_id="demo")
