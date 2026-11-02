"""Phase 6E tests: static analysis, blocked execution, debugging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.dev.test_runner import (
    DevTestRequest,
    analyze_static,
    diagnose,
    persist_report,
    run_tests,
    PROFILE_PYTEST,
    PROFILE_STATIC,
    STATUS_BLOCKED,
    STATUS_ERROR,
    STATUS_FAIL,
    STATUS_PASS,
    redact,
)
from jarvis.dev.workspace import WorkspaceManager


@pytest.fixture
def ws(tmp_path: Path):
    return WorkspaceManager(tmp_path / "ws").create_project("proj")


def test_unknown_profile(ws):
    r = run_tests(ws, DevTestRequest(project_id="p", profile="rm -rf /"))
    assert r.status == STATUS_ERROR
    assert r.code_executed is False


def test_shell_syntax_rejected(ws):
    r = run_tests(ws, DevTestRequest(project_id="p", profile="pytest; rm -rf /"))
    assert r.status == STATUS_ERROR
    assert r.code_executed is False


def test_pytest_blocked(ws):
    r = run_tests(ws, DevTestRequest(project_id="p", profile=PROFILE_PYTEST, execution_permitted=True))
    assert r.status == STATUS_BLOCKED
    assert r.code_executed is False
    assert "isolation" in r.reason


def test_static_valid(ws):
    ws.write_text("src/core.py", "def add(a, b):\n    return a + b\n")
    r = analyze_static(ws, DevTestRequest(project_id="p", related_files=["src/core.py"]))
    assert r.status == STATUS_PASS
    assert r.code_executed is False
    assert r.counts and r.counts["syntax_errors"] == 0


def test_static_syntax_error(ws):
    ws.write_text("src/bad.py", "def broken(:\n")
    r = analyze_static(ws, DevTestRequest(project_id="p", related_files=["src/bad.py"]))
    assert r.status == STATUS_FAIL
    assert r.code_executed is False
    assert "Syntax" in r.failure_summary


def test_missing_file(ws):
    r = analyze_static(ws, DevTestRequest(project_id="p", related_files=["src/missing.py"]))
    assert r.status == STATUS_FAIL
    assert "Missing" in r.failure_summary


def test_static_not_labelled_functional(ws):
    ws.write_text("src/core.py", "x = 1\n")
    r = analyze_static(ws, DevTestRequest(project_id="p", related_files=["src/core.py"]))
    assert "Not functional" in r.limitations or "Syntax check only" in r.limitations


def test_diagnose_blocked_no_apply(ws):
    r = run_tests(ws, DevTestRequest(project_id="p", profile=PROFILE_PYTEST))
    d = diagnose(r)
    assert d.suggestions
    assert all(s.applied is False for s in d.suggestions)
    assert "hypothesis" in d.suggestions[0].hypothesis.lower() or d.suggestions[0].hypothesis


def test_diagnose_fail_preserves_evidence(ws):
    ws.write_text("src/bad.py", "def x(:\n")
    r = analyze_static(ws, DevTestRequest(project_id="p", related_files=["src/bad.py"]))
    d = diagnose(r)
    assert r.failure_summary
    assert d.suggestions[0].evidence == r.failure_summary
    assert d.suggestions[0].applied is False


def test_persist_inside_workspace(ws):
    r = run_tests(ws, DevTestRequest(project_id="p", profile=PROFILE_STATIC))
    persist_report(ws, r)
    assert r.report_path
    assert ws.exists(r.report_path)
    data = json.loads(ws.read_text(r.report_path))
    assert data["code_executed"] is False


def test_redact_secrets():
    text = redact("api_key=sk-abcdefghijklmnopqrstuvwxyz")
    assert "sk-" not in text or "[REDACTED]" in text
