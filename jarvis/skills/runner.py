"""Deterministic bounded task runner for Phase 3 end-to-end learning verification.

This is NOT the Multi-Agent Orchestrator. It executes small, explicit, local
tasks (filesystem / pure computation) so the learning pipeline can be tested
against real execution traces rather than hand-written synthetic dicts.

Safety:
- No network calls
- No shell execution
- No arbitrary code eval
- Secrets in inputs are redacted before persistence
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from jarvis.memory.store import looks_like_secret


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_REDACT = "[REDACTED]"


def redact_text(text: str) -> str:
    """Redact obvious secret-like substrings from free text."""
    if not text:
        return text
    # Key=value style
    text = re.sub(
        r"(?i)(api[_\s-]?key|password|passwd|secret|token|bearer)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9]{20,}\b", _REDACT, text)
    text = re.sub(r"\bAIza[0-9A-Za-z\-_]{20,}\b", _REDACT, text)
    text = re.sub(r"\b(ghp|gho)_[A-Za-z0-9]{20,}\b", _REDACT, text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if looks_like_secret(str(k)) or looks_like_secret(str(v)):
                out[k] = _REDACT
            else:
                out[k] = redact_value(v)
        return out
    return value


@dataclass
class StepResult:
    step: int
    action: str
    tool: str
    ok: bool
    detail: str = ""
    started_at: str = ""
    finished_at: str = ""


@dataclass
class TaskRunResult:
    """Real execution record produced by DeterministicTaskRunner."""

    task_id: str
    objective: str
    task_plan: list[str]
    steps: list[StepResult] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    agents_used: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    test_results: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "unknown"
    notes: str = ""
    started_at: str = ""
    finished_at: str = ""
    workspace: str = ""

    def to_trace(self) -> dict[str, Any]:
        """Convert to LearningPipeline trace dict (already redacted)."""
        procedure = [
            {
                "step": s.step,
                "action": s.action,
                "tool": s.tool,
                "ok": s.ok,
            }
            for s in self.steps
        ]
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "task_plan": list(self.task_plan),
            "tools_used": list(self.tools_used),
            "agents_used": list(self.agents_used),
            "skills_used": list(self.skills_used),
            "errors": list(self.errors),
            "fixes": list(self.fixes),
            "resources": list(self.resources),
            "test_results": list(self.test_results),
            "outcome": self.outcome,
            "notes": self.notes,
            "procedure_hint": procedure,
            "skill_name": self._suggest_skill_name(),
            "skill_category": "local_task",
            "when_to_use": self.objective,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "source": "deterministic_runner",
        }

    def _suggest_skill_name(self) -> str:
        base = re.sub(r"[^a-z0-9]+", "_", self.objective.lower()).strip("_")
        parts = [p for p in base.split("_") if p][:6]
        return "_".join(parts) or "local_task"


class DeterministicTaskRunner:
    """Runs bounded local tasks and records honest outcomes.

    Supported task kinds:
    - text_transform: write input → transform → write output → verify
    - file_checksum: write file → compute sha256 → verify
    - intentional_fail: runs a step that fails on purpose
    """

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    def run(self, task: dict[str, Any]) -> TaskRunResult:
        kind = (task.get("kind") or "text_transform").strip()
        task_id = str(task.get("task_id") or f"run-{_utc_now()}")
        objective = redact_text(str(task.get("objective") or kind))
        result = TaskRunResult(
            task_id=task_id,
            objective=objective,
            task_plan=[],
            agents_used=["deterministic_runner"],
            started_at=_utc_now(),
            workspace=str(self.workspace),
        )

        handlers: dict[str, Callable[[dict[str, Any], TaskRunResult], None]] = {
            "text_transform": self._run_text_transform,
            "file_checksum": self._run_file_checksum,
            "intentional_fail": self._run_intentional_fail,
        }
        handler = handlers.get(kind)
        if handler is None:
            result.errors.append(f"Unknown task kind: {kind}")
            result.outcome = "failure"
            result.test_results.append({"name": "kind_supported", "passed": False})
            result.finished_at = _utc_now()
            return result

        try:
            handler(task, result)
        except Exception as exc:  # pragma: no cover - defensive
            result.errors.append(redact_text(str(exc)))
            result.outcome = "failure"
            result.test_results.append(
                {"name": "uncaught_exception", "passed": False, "detail": redact_text(str(exc))}
            )

        result.finished_at = _utc_now()
        # Final outcome honesty: any failed step or failed test → failure
        if any(not s.ok for s in result.steps) or any(
            not t.get("passed", False) for t in result.test_results
        ):
            result.outcome = "failure"
        elif result.outcome == "unknown":
            result.outcome = "success"
        return result

    # ------------------------------------------------------------------ tasks
    def _run_text_transform(self, task: dict[str, Any], result: TaskRunResult) -> None:
        text = str(task.get("text") or "hello jarvis")
        if looks_like_secret(text):
            # Refuse to process secrets as payload content
            result.errors.append("Input text looks like a secret; refused")
            result.outcome = "failure"
            result.test_results.append({"name": "secret_guard", "passed": False})
            result.task_plan = ["reject_secret_input"]
            return

        mode = (task.get("mode") or "upper").lower()
        result.task_plan = [
            "write_input_file",
            f"transform_{mode}",
            "write_output_file",
            "verify_output",
        ]
        result.tools_used = ["filesystem", "text"]

        in_path = self.workspace / "input.txt"
        out_path = self.workspace / "output.txt"

        # Step 1
        s1_start = _utc_now()
        in_path.write_text(text, encoding="utf-8")
        result.steps.append(
            StepResult(1, "Write input text to input.txt", "filesystem", True, started_at=s1_start, finished_at=_utc_now())
        )

        # Step 2
        s2_start = _utc_now()
        raw = in_path.read_text(encoding="utf-8")
        if mode == "upper":
            transformed = raw.upper()
        elif mode == "lower":
            transformed = raw.lower()
        elif mode == "reverse":
            transformed = raw[::-1]
        else:
            result.steps.append(
                StepResult(2, f"Unknown mode {mode}", "text", False, started_at=s2_start, finished_at=_utc_now())
            )
            result.errors.append(f"Unknown transform mode: {mode}")
            result.test_results.append({"name": "mode_supported", "passed": False})
            return
        result.steps.append(
            StepResult(2, f"Transform text with mode={mode}", "text", True, started_at=s2_start, finished_at=_utc_now())
        )

        # Step 3
        s3_start = _utc_now()
        out_path.write_text(transformed, encoding="utf-8")
        result.steps.append(
            StepResult(3, "Write transformed text to output.txt", "filesystem", True, started_at=s3_start, finished_at=_utc_now())
        )

        # Step 4 verify
        s4_start = _utc_now()
        actual = out_path.read_text(encoding="utf-8")
        ok = actual == transformed and len(actual) == len(raw)
        result.steps.append(
            StepResult(4, "Verify output matches transform", "filesystem", ok, started_at=s4_start, finished_at=_utc_now())
        )
        result.test_results.append({"name": "output_matches", "passed": ok})
        result.test_results.append({"name": "output_exists", "passed": out_path.exists()})
        result.outcome = "success" if ok else "failure"
        if not ok:
            result.errors.append("Output verification failed")

    def _run_file_checksum(self, task: dict[str, Any], result: TaskRunResult) -> None:
        content = str(task.get("content") or "checksum-payload")
        if looks_like_secret(content):
            result.errors.append("Content looks like a secret; refused")
            result.outcome = "failure"
            result.test_results.append({"name": "secret_guard", "passed": False})
            result.task_plan = ["reject_secret_input"]
            return

        result.task_plan = ["write_file", "compute_sha256", "verify_digest_length"]
        result.tools_used = ["filesystem", "hashlib"]
        path = self.workspace / "payload.bin"

        s1 = _utc_now()
        path.write_bytes(content.encode("utf-8"))
        result.steps.append(StepResult(1, "Write payload file", "filesystem", True, started_at=s1, finished_at=_utc_now()))

        s2 = _utc_now()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result.steps.append(
            StepResult(2, f"Compute sha256 ({digest[:12]}…)", "hashlib", True, started_at=s2, finished_at=_utc_now())
        )

        s3 = _utc_now()
        ok = len(digest) == 64
        result.steps.append(StepResult(3, "Verify digest length == 64", "hashlib", ok, started_at=s3, finished_at=_utc_now()))
        result.test_results.append({"name": "digest_len_64", "passed": ok})
        result.outcome = "success" if ok else "failure"

    def _run_intentional_fail(self, task: dict[str, Any], result: TaskRunResult) -> None:
        result.task_plan = ["prepare", "failing_step"]
        result.tools_used = ["filesystem"]
        s1 = _utc_now()
        marker = self.workspace / "attempted.txt"
        marker.write_text("started", encoding="utf-8")
        result.steps.append(StepResult(1, "Prepare workspace marker", "filesystem", True, started_at=s1, finished_at=_utc_now()))

        s2 = _utc_now()
        # Real failure: required output file is never created
        missing = self.workspace / "must_exist.txt"
        ok = missing.exists()  # False
        result.steps.append(
            StepResult(
                2,
                "Require must_exist.txt (intentionally absent)",
                "filesystem",
                ok,
                detail="file missing",
                started_at=s2,
                finished_at=_utc_now(),
            )
        )
        result.errors.append("must_exist.txt was not created")
        result.test_results.append({"name": "must_exist", "passed": False})
        result.outcome = "failure"
