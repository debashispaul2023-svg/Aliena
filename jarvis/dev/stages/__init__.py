"""Phase 6C stage modules.

Deterministic offline requirements, architecture, and planning.
Does not generate code, run subprocesses, or install packages.
"""

from .requirements import analyze_requirements, RequirementsResult
from .architecture import design_architecture, ArchitectureResult
from .planning import (
    PlanItem,
    ImplementationPlan,
    build_plan,
    PlanningResult,
    PLAN_PENDING,
    PLAN_BLOCKED,
)
from .pipeline import run_pipeline, PipelineResult

__all__ = [
    "analyze_requirements",
    "RequirementsResult",
    "design_architecture",
    "ArchitectureResult",
    "PlanItem",
    "ImplementationPlan",
    "build_plan",
    "PlanningResult",
    "PLAN_PENDING",
    "PLAN_BLOCKED",
    "run_pipeline",
    "PipelineResult",
]
