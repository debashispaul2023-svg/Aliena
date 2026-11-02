"""Architecture design stage (Phase 6C).

Produces a DesignDoc from a validated RequirementSpec.
Does not verify external services or generate code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.dev.models import (
    DesignDoc,
    ModelValidationError,
    RequirementSpec,
    SPEC_READY,
)
from jarvis.dev.stages.requirements import RequirementsResult


@dataclass
class ArchitectureResult:
    design: Optional[DesignDoc]
    success: bool
    error: Optional[str] = None
    notes: str = ""
    traced_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "design": self.design.to_dict() if self.design else None,
            "success": self.success,
            "error": self.error,
            "notes": self.notes,
            "traced_criteria": list(self.traced_criteria),
        }


def design_architecture(spec: RequirementSpec) -> ArchitectureResult:
    """Build a design document traceable to the requirement criteria."""
    if spec is None:
        return ArchitectureResult(
            design=None, success=False, error="RequirementSpec is required"
        )
    if spec.status != SPEC_READY:
        return ArchitectureResult(
            design=None,
            success=False,
            error=f"Requirements not ready (status={spec.status})",
            notes="Architecture requires a complete RequirementSpec.",
        )
    if not spec.acceptance_criteria:
        return ArchitectureResult(
            design=None,
            success=False,
            error="No acceptance criteria to trace",
        )

    functional_ids = [
        c.criterion_id
        for c in spec.acceptance_criteria
        if c.description.startswith("Functional behavior is implemented:")
    ]
    nfr_ids = [
        c.criterion_id
        for c in spec.acceptance_criteria
        if c.criterion_id not in functional_ids
    ]
    components = [
        {
            "name": "input",
            "responsibility": "Accept and validate the user request",
            "traces": functional_ids[:1] or [spec.acceptance_criteria[0].criterion_id],
        },
        {
            "name": "core_logic",
            "responsibility": "Implement: " + "; ".join(spec.functional or [spec.user_request]),
            "traces": functional_ids or [c.criterion_id for c in spec.acceptance_criteria],
        },
        {
            "name": "verification",
            "responsibility": "Check acceptance criteria",
            "traces": [c.criterion_id for c in spec.acceptance_criteria],
        },
    ]
    if nfr_ids:
        components.append(
            {
                "name": "non_functional",
                "responsibility": "Address: " + "; ".join(spec.non_functional or ["stated NFRs"]),
                "traces": nfr_ids,
            }
        )
    if spec.constraints:
        components.append(
            {
                "name": "constraints",
                "responsibility": "Honor constraints: " + "; ".join(spec.constraints),
                "traces": functional_ids[:1] or [spec.acceptance_criteria[0].criterion_id],
            }
        )
    interfaces = [
        {
            "from": "input",
            "to": "core_logic",
            "contract": "validated request structure",
        },
        {
            "from": "core_logic",
            "to": "verification",
            "contract": "deliverable plus criterion ids",
        },
    ]
    decisions = [
        "Keep modules small and deterministic for offline tests.",
        "Do not add a new database in this phase.",
    ]
    trade_offs = [
        "Deterministic heuristics trade coverage for reproducibility.",
    ]
    security = [
        "Application-level path boundaries only; not an OS sandbox.",
        "Do not execute untrusted content.",
        "Do not store secrets in artifacts.",
    ]
    limitations = [
        "Design is a proposal, not a verified deployment.",
        "External services are not claimed verified.",
    ]
    if spec.constraints:
        limitations.extend([f"Constraint: {c}" for c in spec.constraints])

    try:
        design = DesignDoc(
            project_id=spec.project_id,
            overview=spec.user_request,
            components=components,
            data_flow=[
                "user request",
                "requirements",
                "core_logic",
                "verification",
            ],
            interfaces=interfaces,
            decisions=decisions,
            trade_offs=trade_offs,
            security_considerations=security,
            limitations=limitations,
        )
    except ModelValidationError as exc:
        return ArchitectureResult(design=None, success=False, error=str(exc))

    return ArchitectureResult(
        design=design,
        success=True,
        notes="Design produced from requirements; not an implementation.",
        traced_criteria=[c.criterion_id for c in spec.acceptance_criteria],
    )
