"""Phase 6H: offline intelligence tests. Does not execute generated code."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.intelligence import (
    detect_contradictions,
    detect_project_type,
    local_import_findings,
)
from jarvis.dev.stages import analyze_requirements
from jarvis.dev.workspace import WorkspaceManager


def test_project_type_distinct():
    assert detect_project_type("Build a CLI that lists files") == "cli"
    assert detect_project_type("Build a hello function") == "function"
    assert detect_project_type("Build a library package") == "library"


def test_contradiction_blocks_ready():
    issues = detect_contradictions("Language is Python. Build a hello function offline and must use network with unit tests.")
    assert issues
    r = analyze_requirements("Language is Python. Build a hello function offline and must use network with unit tests.")
    assert r.complete is False
    assert any("contradiction" in q.lower() for q in (r.spec.clarifying_questions if r.spec else []))


def test_unresolved_import(tmp_path: Path):
    ws = WorkspaceManager(tmp_path / "ws").create_project("imp")
    ws.write_text("src/core.py", "from missingmod import foo\n")
    findings = local_import_findings(ws, ["src/core.py"])
    assert any("unresolved_import" in f for f in findings)


def test_vague_still_blocked():
    r = analyze_requirements("Make it good and make it fast.")
    assert r.complete is False


def test_contradiction_wording_variants():
    assert detect_contradictions("Work offline. Must use the network.")
    assert detect_contradictions("Offline only. Requires network access.")


def test_force_ready_records_override(tmp_path: Path):
    from jarvis.dev.integration import run_dev_workflow
    ws = WorkspaceManager(tmp_path / "ws").create_project("ovr")
    report = run_dev_workflow(
        "Language is Python. Build a hello function offline and must use network with unit tests.",
        ws,
        force_ready=True,
    )
    assert any("force_ready" in x for x in report.limitations)
    assert "OVERRIDE" in report.qa_summary or "override" in report.qa_summary.lower()
    assert report.runtime_tests is not None
    assert report.runtime_tests.status == "BLOCKED"
    assert report.runtime_tests.code_executed is False
