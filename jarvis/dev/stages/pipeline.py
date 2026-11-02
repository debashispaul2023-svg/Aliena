"""Phase 6C pipeline: Requirements → Architecture → Planning.

Focused coordinator only. Not wired to the full Jarvis orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.dev.models import DesignDoc, RequirementSpec
from jarvis.dev.stages.architecture import ArchitectureResult, design_architecture
from jarvis.dev.stages.planning import ImplementationPlan, PlanningResult, build_plan
from jarvis.dev.stages.requirements import RequirementsResult, analyze_requirements


@dataclass
class PipelineResult:
    requirements: Optional[RequirementsResult] = None
    architecture: Optional[ArchitectureResult] = None
    planning: Optional[PlanningResult] = None
    success: bool = False
    incomplete: bool = False
    error: Optional[str] = None
    stages_completed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirements": self.requirements.to_dict() if self.requirements else None,
            "architecture": self.architecture.to_dict() if self.architecture else None,
            "planning": self.planning.to_dict() if self.planning else None,
            "success": self.success,
            "incomplete": self.incomplete,
            "error": self.error,
            "stages_completed": list(self.stages_completed),
        }


def run_pipeline(
    user_request: str,
    *,
    project_id: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> PipelineResult:
    """Run the three stages in order. Stops on incomplete requirements."""
    result = PipelineResult()
    req = analyze_requirements(
        user_request, project_id=project_id, context=context
    )
    result.requirements = req
    if req.error or req.spec is None:
        result.error = req.error or "requirements failed"
        return result
    result.stages_completed.append("requirements")
    if not req.complete:
        result.incomplete = True
        result.error = "Requirements incomplete; architecture and planning skipped"
        return result

    arch = design_architecture(req.spec)
    result.architecture = arch
    if not arch.success or arch.design is None:
        result.error = arch.error or "architecture failed"
        return result
    result.stages_completed.append("architecture")

    plan = build_plan(req.spec, arch.design)
    result.planning = plan
    if not plan.success or plan.plan is None:
        result.error = plan.error or "planning failed"
        return result
    result.stages_completed.append("planning")
    result.success = True
    return result
