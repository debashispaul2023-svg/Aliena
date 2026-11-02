"""Learning pipeline: execution trace → experience → skill candidate → validation.

Generated skills store structured, reviewable procedures. They do NOT execute
arbitrary code. Activation requires explicit verification.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .experience import ExperienceStore
from .models import (
    Experience,
    Skill,
    STATUS_PROPOSED,
    STATUS_VALIDATING,
    STATUS_VERIFIED,
    STATUS_ACTIVE,
    STATUS_REJECTED,
)
from .registry import SkillRegistry


def json_dumps_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def make_synthetic_trace(
    objective: str = "Process a PDF and extract text tables",
    success: bool = True,
) -> dict[str, Any]:
    """Synthetic execution trace for pipeline demos and unit tests.

    This is NOT a real agent run. Callers must not treat it as production evidence
    beyond testing the learning pipeline plumbing.
    """
    return {
        "task_id": "synthetic-task-001",
        "objective": objective,
        "task_plan": [
            "Locate PDF file",
            "Extract text with pdf library",
            "Parse tables",
            "Write CSV output",
            "Run verification checks",
        ],
        "tools_used": ["filesystem", "pdf_reader", "code"],
        "agents_used": ["coder", "tester"],
        "skills_used": [],
        "errors": [] if success else ["pdfminer failed on scanned page"],
        "fixes": [] if success else ["switched to OCR fallback"],
        "resources": ["https://docs.python.org/3/library/"],
        "test_results": [
            {"name": "output_exists", "passed": success},
            {"name": "row_count_gt_0", "passed": success},
        ],
        "outcome": "success" if success else "failure",
        "notes": "Synthetic trace for learning pipeline unit tests only.",
        "procedure_hint": [
            {"step": 1, "action": "Open PDF from path", "tool": "filesystem"},
            {"step": 2, "action": "Extract text/tables", "tool": "pdf_reader"},
            {"step": 3, "action": "Normalize rows to CSV", "tool": "code"},
            {"step": 4, "action": "Validate row count > 0", "tool": "code"},
        ],
        "skill_name": "pdf_table_extraction",
        "skill_category": "document",
        "when_to_use": "When the user asks to extract tables or structured data from a PDF",
    }


class LearningPipeline:
    """Orchestrates experience recording and skill-candidate creation.

    Does not run agents. Accepts a caller-supplied execution trace dict.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        experiences: ExperienceStore,
    ) -> None:
        self.registry = registry
        self.experiences = experiences

    def record_experience_from_trace(
        self, trace: dict[str, Any], idempotent: bool = False
    ) -> Experience:
        """Persist an experience from a structured trace. Outcome must be explicit."""
        outcome = (trace.get("outcome") or "unknown").lower()
        return self.experiences.record(
            task_id=str(trace.get("task_id") or ""),
            objective=str(trace.get("objective") or ""),
            task_plan=list(trace.get("task_plan") or []),
            tools_used=list(trace.get("tools_used") or []),
            agents_used=list(trace.get("agents_used") or []),
            skills_used=list(trace.get("skills_used") or []),
            errors=list(trace.get("errors") or []),
            fixes=list(trace.get("fixes") or []),
            resources=list(trace.get("resources") or []),
            test_results=list(trace.get("test_results") or []),
            outcome=outcome,
            notes=str(trace.get("notes") or ""),
            completed=True,
            idempotent=idempotent,
        )

    def propose_skill_from_trace(
        self, trace: dict[str, Any], require_success: bool = True
    ) -> Optional[Skill]:
        """Analyze a trace and create a PROPOSED skill candidate.

        By default only successful outcomes produce candidates.
        Procedure is taken from structured steps in the trace (or derived
        from task_plan as non-executable reviewable steps).
        Does not activate the skill. Rejects traces that embed secrets.
        """
        from jarvis.memory.store import looks_like_secret

        outcome = (trace.get("outcome") or "unknown").lower()
        if require_success and outcome != "success":
            return None

        # Prefer explicit structured procedure; fall back to task_plan strings
        procedure = trace.get("procedure_hint")
        if not procedure:
            procedure = [
                {"step": i + 1, "action": step, "tool": None}
                for i, step in enumerate(trace.get("task_plan") or [])
            ]
        if not procedure:
            return None

        # Refuse skill proposals that still contain secrets in text fields
        blob = json_dumps_safe(trace)
        if looks_like_secret(blob):
            return None

        name = (trace.get("skill_name") or "").strip()
        if not name:
            obj = (trace.get("objective") or "learned_skill").strip().lower()
            name = "_".join(obj.split()[:5]) or "learned_skill"

        # Idempotent skill proposal: if a skill already exists for this source_task, return it
        source_task = str(trace.get("task_id") or "")
        if source_task:
            existing = self.registry.search(query=source_task, limit=20)
            for s in existing:
                if s.source_task == source_task and s.name == name:
                    return s
            # also scan by name+source via list
            for s in self.registry.list_by_name(name):
                if s.source_task == source_task:
                    return s

        tests = []
        for tr in trace.get("test_results") or []:
            if isinstance(tr, dict):
                tests.append(
                    {
                        "name": tr.get("name", "check"),
                        "expect_passed": bool(tr.get("passed", False)),
                    }
                )

        clean_procedure = []
        for step in procedure:
            if isinstance(step, dict):
                clean_procedure.append(
                    {
                        "step": step.get("step"),
                        "action": str(step.get("action") or step.get("description") or ""),
                        "tool": step.get("tool"),
                        "ok": step.get("ok"),
                    }
                )
            else:
                clean_procedure.append({"step": len(clean_procedure) + 1, "action": str(step), "tool": None})

        skill = self.registry.create_skill(
            name=name,
            description=f"Learned from task: {trace.get('objective', '')}",
            category=str(trace.get("skill_category") or "learned"),
            when_to_use=str(trace.get("when_to_use") or trace.get("objective") or ""),
            prerequisites=[],
            required_tools=list(trace.get("tools_used") or []),
            procedure=clean_procedure,
            examples=[str(trace.get("objective") or "")],
            known_failures=list(trace.get("errors") or []),
            successful_patterns=list(trace.get("fixes") or [])
            + [p for p in (trace.get("successful_patterns") or [])],
            validation_tests=tests,
            confidence=0.55 if outcome == "success" else 0.3,
            source_task=source_task,
            tags=["learned", "auto_candidate"],
            status=STATUS_PROPOSED,
        )
        return skill

    def validate_candidate(
        self, skill_id: str, structural_only: bool = True
    ) -> tuple[bool, list[str], Optional[Skill]]:
        """Run structural validation and transition status accordingly.

        Full agent/runtime validation is deferred to the orchestrator phase.
        structural_only=True is the supported path in this phase.
        Idempotent for already VERIFIED/ACTIVE skills.
        """
        skill = self.registry.get(skill_id)
        if not skill:
            return False, ["Skill not found"], None

        ok, failures = self.registry.run_structural_validation(skill_id)

        if skill.status in (STATUS_VERIFIED, STATUS_ACTIVE):
            if ok:
                return True, [], skill
            if skill.status == STATUS_ACTIVE:
                self.registry.deactivate(skill_id)
            rejected = self.registry.mark_rejected(
                skill_id, reason="; ".join(failures)
            )
            return False, failures, rejected

        if skill.status == STATUS_REJECTED:
            return False, failures or ["already rejected"], skill

        if skill.status == STATUS_PROPOSED:
            self.registry.start_validation(skill_id)

        if ok:
            verified = self.registry.mark_verified(skill_id)
            return True, [], verified
        rejected = self.registry.mark_rejected(
            skill_id, reason="; ".join(failures)
        )
        return False, failures, rejected

    def run_pipeline(
        self,
        trace: dict[str, Any],
        auto_validate: bool = True,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        """Full pipeline for a single trace.

        Returns a result dict with experience, candidate skill, and validation
        outcome. Does not activate skills automatically.
        """
        exp = self.record_experience_from_trace(trace, idempotent=idempotent)
        candidate = self.propose_skill_from_trace(trace)
        result: dict[str, Any] = {
            "experience_id": exp.experience_id,
            "task_id": exp.task_id,
            "outcome": exp.outcome,
            "skill_id": None,
            "skill_status": None,
            "validated": False,
            "failures": [],
        }
        if not candidate:
            result["failures"] = [
                "No skill candidate (failed outcome, empty procedure, or secret content)"
            ]
            return result

        result["skill_id"] = candidate.skill_id
        result["skill_status"] = candidate.status

        if auto_validate:
            ok, failures, final = self.validate_candidate(candidate.skill_id)
            result["validated"] = ok
            result["failures"] = failures
            if final:
                result["skill_status"] = final.status
        return result

    def run_from_task_result(
        self, task_result: Any, auto_validate: bool = True, idempotent: bool = True
    ) -> dict[str, Any]:
        """Accept a DeterministicTaskRunner TaskRunResult (or object with to_trace())."""
        if hasattr(task_result, "to_trace"):
            trace = task_result.to_trace()
        elif isinstance(task_result, dict):
            trace = task_result
        else:
            raise TypeError("task_result must provide to_trace() or be a dict")
        return self.run_pipeline(trace, auto_validate=auto_validate, idempotent=idempotent)
