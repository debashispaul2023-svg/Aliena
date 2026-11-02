"""Phase 6E: controlled test runner, static analysis, and debugging.

Execution of generated code is BLOCKED unless a verified OS isolation
boundary is available and explicitly enabled. The Phase 6B path jail is
not an OS sandbox. This module does not run untrusted project code.
"""

from __future__ import annotations

import ast
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.dev.codegen import GenerationResult
from jarvis.dev.workspace import DevWorkspace, WorkspaceError

SCHEMA_VERSION = "1.0"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_BLOCKED = "BLOCKED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_ERROR = "ERROR"

# Allowlisted profiles. None of these execute untrusted code in this phase.
PROFILE_STATIC = "static_analysis"
PROFILE_PYTEST = "pytest"
SUPPORTED_PROFILES = {PROFILE_STATIC, PROFILE_PYTEST}

# Isolation is not verified in this environment.
ISOLATION_AVAILABLE = False
ISOLATION_MECHANISM = "none"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def redact(text: str) -> str:
    if not text:
        return text
    text = re.sub(
        r"(?i)(api[_\s-]?key|password|secret|token|bearer)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9]{20,}\b", "[REDACTED]", text)
    return text


@dataclass
class DevTestRequest:
    project_id: str
    profile: str = PROFILE_STATIC
    related_files: list[str] = field(default_factory=list)
    plan_task_ids: list[str] = field(default_factory=list)
    criterion_ids: list[str] = field(default_factory=list)
    timeout_seconds: int = 30
    execution_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestResult:
    run_id: str
    project_id: str
    profile: str
    status: str
    code_executed: bool = False
    exit_code: Optional[int] = None
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    counts: Optional[dict[str, int]] = None
    isolation: str = ISOLATION_MECHANISM
    isolation_verified: bool = False
    failure_summary: str = ""
    evidence: list[str] = field(default_factory=list)
    limitations: str = ""
    reason: str = ""
    report_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DebugSuggestion:
    hypothesis: str
    evidence: str
    proposed_change: str
    plan_task_ids: list[str] = field(default_factory=list)
    criterion_ids: list[str] = field(default_factory=list)
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DebugReport:
    run_id: str
    status: str
    suggestions: list[DebugSuggestion] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_static(workspace: DevWorkspace, request: DevTestRequest) -> TestResult:
    """Parse Python sources with ast.parse. Does not import or execute them."""
    started = _utcnow()
    result = TestResult(
        run_id=_new_id("run_"),
        project_id=request.project_id,
        profile=PROFILE_STATIC,
        status=STATUS_PASS,
        code_executed=False,
        started_at=started,
        isolation="not_applicable",
        isolation_verified=False,
        limitations="Syntax check only. Not functional correctness.",
    )
    files = request.related_files or workspace.list_files()
    py_files = [f for f in files if f.endswith(".py")]
    errors: list[str] = []
    missing: list[str] = []
    for rel in py_files:
        try:
            text = workspace.read_text(rel)
        except WorkspaceError:
            missing.append(rel)
            continue
        try:
            ast.parse(text, filename=rel)
            result.evidence.append(f"syntax_ok:{rel}")
        except SyntaxError as exc:
            errors.append(f"{rel}:{exc.lineno}:{exc.msg}")
            result.evidence.append(f"syntax_error:{rel}")
    if missing:
        result.status = STATUS_FAIL
        result.failure_summary = "Missing files: " + ", ".join(missing)
    elif errors:
        result.status = STATUS_FAIL
        result.failure_summary = "Syntax errors: " + "; ".join(errors)
    else:
        result.failure_summary = ""
        result.counts = {"files_checked": len(py_files), "syntax_errors": 0}
    result.finished_at = _utcnow()
    result.reason = "static_analysis_only"
    return result


def run_tests(workspace: DevWorkspace, request: DevTestRequest) -> TestResult:
    """Dispatch a test profile. Execution profiles are BLOCKED without isolation."""
    if request.profile not in SUPPORTED_PROFILES:
        return TestResult(
            run_id=_new_id("run_"),
            project_id=request.project_id,
            profile=request.profile,
            status=STATUS_ERROR,
            code_executed=False,
            reason="unknown_profile",
            failure_summary="Unknown test profile",
            isolation=ISOLATION_MECHANISM,
            isolation_verified=False,
        )
    # Reject shell-like profiles even if someone passes them as the profile string
    if any(tok in request.profile for tok in (";", "|", "&", ">", "<", "`", "$(")):
        return TestResult(
            run_id=_new_id("run_"),
            project_id=request.project_id,
            profile=request.profile,
            status=STATUS_ERROR,
            code_executed=False,
            reason="shell_syntax_rejected",
            failure_summary="Shell syntax is not allowed",
        )
    if request.profile == PROFILE_STATIC:
        return analyze_static(workspace, request)
    # pytest or any executing profile
    return TestResult(
        run_id=_new_id("run_"),
        project_id=request.project_id,
        profile=request.profile,
        status=STATUS_BLOCKED,
        code_executed=False,
        reason="isolation_unavailable",
        failure_summary=(
            "Execution blocked: no verified OS isolation "
            "(docker/podman/bwrap/firejail not available). "
            "Workspace path jail is not a sandbox."
        ),
        isolation=ISOLATION_MECHANISM,
        isolation_verified=False,
        limitations="Host execution of generated code is refused.",
        started_at=_utcnow(),
        finished_at=_utcnow(),
    )


def diagnose(result: TestResult) -> DebugReport:
    """Propose fixes from evidence. Does not modify files or re-execute."""
    suggestions: list[DebugSuggestion] = []
    if result.status == STATUS_BLOCKED:
        suggestions.append(
            DebugSuggestion(
                hypothesis="Execution is blocked because OS isolation is unavailable.",
                evidence=result.reason or "isolation_unavailable",
                proposed_change="Keep static analysis only until isolation is verified.",
                plan_task_ids=list(),
                applied=False,
            )
        )
    elif result.status == STATUS_FAIL and result.failure_summary:
        suggestions.append(
            DebugSuggestion(
                hypothesis="Syntax or missing-file issue is indicated by static evidence.",
                evidence=result.failure_summary,
                proposed_change="Review the listed files and correct syntax or add missing files via Phase 6D authorization.",
                applied=False,
            )
        )
    elif result.status == STATUS_ERROR:
        suggestions.append(
            DebugSuggestion(
                hypothesis="Request was invalid or unsupported.",
                evidence=result.reason or result.failure_summary,
                proposed_change="Use an allowlisted profile.",
                applied=False,
            )
        )
    else:
        suggestions.append(
            DebugSuggestion(
                hypothesis="No failure evidence to diagnose.",
                evidence=result.status,
                proposed_change="No change proposed.",
                applied=False,
            )
        )
    return DebugReport(
        run_id=result.run_id,
        status=result.status,
        suggestions=suggestions,
        notes="Hypotheses only. No files were modified and no code was executed.",
    )


def persist_report(workspace: DevWorkspace, result: TestResult) -> TestResult:
    """Save a redacted report inside the project workspace."""
    try:
        payload = result.to_dict()
        payload["schema_version"] = SCHEMA_VERSION
        payload["timestamp"] = _utcnow()
        payload["stdout"] = redact(payload.get("stdout") or "")
        payload["stderr"] = redact(payload.get("stderr") or "")
        path = f"artifacts/test_{result.run_id}.json"
        workspace.write_text(path, json.dumps(payload, indent=2), overwrite=True)
        result.report_path = path
    except Exception as exc:
        result.status = STATUS_ERROR if result.status == STATUS_PASS else result.status
        result.failure_summary = (
            (result.failure_summary + "; " if result.failure_summary else "")
            + f"Report persistence failed: {exc}"
        )
    return result
