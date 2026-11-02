"""Requirements analysis stage (Phase 6C).

Deterministic offline extraction. Does not claim full NLP understanding.
Explicit phrases are recorded as user requirements; other items are
assumptions or clarifying questions, never silently confirmed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.dev.intelligence import detect_contradictions
from jarvis.dev.models import (
    AcceptanceCriterion,
    ModelValidationError,
    RequirementSpec,
    SPEC_BLOCKED,
    SPEC_DRAFT,
    SPEC_READY,
    VERIFY_INSPECTION,
    VERIFY_UNIT_TEST,
)


@dataclass
class RequirementsResult:
    spec: Optional[RequirementSpec]
    complete: bool
    error: Optional[str] = None
    notes: str = ""
    inferred: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict() if self.spec else None,
            "complete": self.complete,
            "error": self.error,
            "notes": self.notes,
            "inferred": list(self.inferred),
        }


_NFR_HINTS = (
    "performance",
    "latency",
    "security",
    "reliable",
    "reliability",
    "scalability",
    "maintainab",
    "offline",
    "timeout",
)
_CONSTRAINT_HINTS = (
    "must not",
    "do not",
    "without ",
    "no install",
    "stdlib",
    "offline only",
    "no database",
    "no gui",
)
_AMBIGUOUS = (
    "something",
    "whatever",
    "etc",
    "and so on",
    "maybe",
    "not sure",
)
_VAGUE = (
    "make it good",
    "make it fast",
    "make it nice",
    "make it better",
    "improve it",
    "do it well",
    "as good as possible",
)


def analyze_requirements(
    user_request: str,
    *,
    project_id: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> RequirementsResult:
    """Build a RequirementSpec from a user request.

    Capability limit: heuristic sentence split and keyword cues.
    Does not invent confirmed requirements. Ambiguity yields questions
    and SPEC_BLOCKED when the request is too thin to plan.
    """
    request = (user_request or "").strip()
    if not request:
        return RequirementsResult(
            spec=None,
            complete=False,
            error="user_request is empty",
            notes="Critical information missing.",
        )

    context = context or {}
    sentences = [
        s.strip()
        for s in re.split(r"[.\n;]+", request)
        if s.strip()
    ]
    functional: list[str] = []
    non_functional: list[str] = []
    constraints: list[str] = []
    assumptions: list[str] = []
    questions: list[str] = []
    inferred: list[str] = []

    for sentence in sentences:
        low = sentence.lower()
        if any(h in low for h in _CONSTRAINT_HINTS):
            constraints.append(sentence)
        elif any(h in low for h in _NFR_HINTS):
            non_functional.append(sentence)
        else:
            functional.append(sentence)

    if not functional and not non_functional:
        functional.append(request)

    if len(request) < 12:
        questions.append("Please describe the goal in more detail.")
    if any(tok in request.lower() for tok in _AMBIGUOUS):
        questions.append("Which specific behaviors are required?")
    if any(tok in request.lower() for tok in _VAGUE):
        questions.append(
            "Acceptance criteria are too vague to verify "
            "(avoid 'good'/'fast' without a measurable target)."
        )
    for issue in detect_contradictions(request):
        questions.append(issue)
        constraints.append(issue)
    if "language" not in request.lower() and context.get("language") is None:
        assumptions.append("Assumption: Python 3 is the implementation language (confirm).")
        questions.append("Which language/runtime should the project target?")
    if "test" not in request.lower():
        assumptions.append("Assumption: unit tests will be used for verification (confirm).")

    criteria: list[AcceptanceCriterion] = []
    for i, item in enumerate(functional, start=1):
        criteria.append(
            AcceptanceCriterion(
                description=f"Functional behavior is implemented: {item}",
                verification_method=VERIFY_UNIT_TEST,
                required=True,
            )
        )
    for item in non_functional:
        criteria.append(
            AcceptanceCriterion(
                description=f"Non-functional property holds: {item}",
                verification_method=VERIFY_INSPECTION,
                required=True,
            )
        )
    if not criteria:
        criteria.append(
            AcceptanceCriterion(
                description="User request is addressed with a documented deliverable.",
                verification_method=VERIFY_INSPECTION,
                required=True,
            )
        )

    complete = not questions
    status = SPEC_READY if complete else SPEC_BLOCKED
    try:
        spec = RequirementSpec(
            user_request=request,
            project_id=project_id or "",
            functional=functional,
            non_functional=non_functional,
            constraints=constraints,
            assumptions=assumptions,
            clarifying_questions=questions,
            acceptance_criteria=criteria,
            status=status,
            metadata={
                "stage": "requirements",
                "mode": "deterministic_offline",
                "inferred_count": len(inferred),
            },
        )
    except ModelValidationError as exc:
        return RequirementsResult(
            spec=None,
            complete=False,
            error=str(exc),
        )

    return RequirementsResult(
        spec=spec,
        complete=complete,
        notes=(
            "Requirements ready for architecture."
            if complete
            else "Unresolved clarifying questions; not marked complete."
        ),
        inferred=inferred,
    )
