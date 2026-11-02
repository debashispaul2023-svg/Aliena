"""Phase 6G: offline development workflow integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.integration import run_dev_workflow
from jarvis.dev.workspace import WorkspaceManager


@pytest.fixture
def ws(tmp_path: Path):
    return WorkspaceManager(tmp_path / "ws").create_project("integ")


def test_successful_offline_flow(ws):
    report = run_dev_workflow(
        "Language is Python. Build a hello function with unit tests.",
        ws,
        force_ready=True,
    )
    assert report.success is False  # placeholder-only is not a verified implementation
    assert "PLACEHOLDER" in report.qa_summary
    assert "generation" in report.stages_completed
    assert "static_analysis" in report.stages_completed
    assert report.execution_blocked is True
    assert report.runtime_tests is not None
    assert report.runtime_tests.status == "BLOCKED"
    assert report.runtime_tests.code_executed is False
    assert report.static_analysis is not None
    assert "not runtime" in report.qa_summary.lower() or "BLOCKED" in report.qa_summary


def test_incomplete_requirements_stop(ws):
    report = run_dev_workflow("Build something maybe", ws, force_ready=False)
    assert report.success is False
    assert report.generation is None
    assert "incomplete" in (report.error or "").lower()


def test_traceability(ws):
    report = run_dev_workflow(
        "Language is Python. Build a hello function with unit tests.",
        ws,
        force_ready=True,
    )
    assert report.success is False
    files = [f.path for f in report.generation.files if f.status == "applied"]
    assert "src/core.py" in files
    assert report.generation.files[0].criterion_ids or report.generation.files[0].plan_task_ids


def test_static_findings_to_diagnosis(ws):
    report = run_dev_workflow(
        "Language is Python. Build a hello function with unit tests.",
        ws,
        force_ready=True,
    )
    assert report.diagnosis is not None
    assert report.diagnosis.suggestions
    assert all(s.applied is False for s in report.diagnosis.suggestions)


def test_runtime_never_pass(ws):
    report = run_dev_workflow(
        "Language is Python. Build a hello function with unit tests.",
        ws,
        force_ready=True,
    )
    assert report.runtime_tests.status == "BLOCKED"
    assert report.runtime_tests.code_executed is False
    assert "PASS" not in (report.runtime_tests.status or "")


def test_static_failure_in_qa(ws, monkeypatch):
    from jarvis.dev.test_runner import TestResult, STATUS_FAIL

    def fake_static(workspace, request):
        return TestResult(
            run_id="run_fake",
            project_id=request.project_id,
            profile="static_analysis",
            status=STATUS_FAIL,
            code_executed=False,
            failure_summary="Syntax errors: src/core.py:1:invalid syntax",
            reason="static_analysis_only",
        )

    monkeypatch.setattr("jarvis.dev.integration.analyze_static", fake_static)
    report = run_dev_workflow(
        "Language is Python. Build a hello function with unit tests.",
        ws,
        force_ready=True,
    )
    assert report.success is False
    assert "STATIC ANALYSIS" in report.qa_summary
    assert "Syntax errors" in report.qa_summary
    assert report.diagnosis is not None
    assert report.runtime_tests.status == "BLOCKED"
    assert report.runtime_tests.code_executed is False
