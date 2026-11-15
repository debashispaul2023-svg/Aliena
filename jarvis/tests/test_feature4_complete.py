"""Feature 4 completion tests. No generated code is executed."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.drafts import apply_approved_draft, approve_code_draft, create_code_draft
from jarvis.dev.lint_plan import lint_files, validate_test_plan
from jarvis.dev.workspace import DevWorkspace


def test_draft_approval_fingerprint(tmp_path: Path):
    ws = DevWorkspace(tmp_path, "demo")
    ws.write_text("notes.py", "old\n")
    change = type("C", (), {"path": "notes.py", "content": "new\n", "overwrite": True})()
    draft = create_code_draft(ws, [change], project_id="demo")
    assert draft.status == "REVIEW_REQUIRED"
    with pytest.raises(Exception):
        apply_approved_draft(ws, draft)
    approve_code_draft(draft, reviewer="reviewer", fingerprint=draft.fingerprint)
    written = apply_approved_draft(ws, draft)
    assert written == ["notes.py"]
    assert ws.read_text("notes.py") == "new\n"


def test_tamper_invalidates_approval(tmp_path: Path):
    ws = DevWorkspace(tmp_path, "demo")
    ws.write_text("notes.py", "old\n")
    change = type("C", (), {"path": "notes.py", "content": "new\n", "overwrite": True})()
    draft = create_code_draft(ws, [change], project_id="demo")
    approve_code_draft(draft, reviewer="reviewer", fingerprint=draft.fingerprint)
    draft.files[0].proposed_content = "tampered\n"
    with pytest.raises(Exception):
        apply_approved_draft(ws, draft)


def test_lint_detects_dangerous_import():
    report = lint_files([("x.py", "import os\nprint(1)\n")])
    assert any(f.code == "dangerous_import" for f in report.findings)


def test_test_plan_does_not_execute(tmp_path: Path):
    errors = validate_test_plan({"tests": ["missing.py"]}, tmp_path)
    assert any("missing" in e for e in errors)
