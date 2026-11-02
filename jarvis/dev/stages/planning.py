"""Implementation planning stage (Phase 6C).

Produces a dependency-aware plan. Does not execute commands,
install packages, or generate application code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.dev.models import DesignDoc, RequirementSpec


PLAN_PENDING = "PENDING"
PLAN_READY = "READY"
PLAN_BLOCKED = "BLOCKED"
PLAN_STATUSES = {PLAN_PENDING, PLAN_READY, PLAN_BLOCKED}


class PlanningError(ValueError):
    """Invalid plan structure."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PlanItem:
    task_id: str
    description: str
    rationale: str = ""
    related_criteria: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    verification_method: str = "inspection"
    completion_conditions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    required: bool = True
    status: str = PLAN_PENDING

    def __post_init__(self) -> None:
        if not self.task_id or not self.task_id.strip():
            raise PlanningError("task_id is required")
        if not self.description or not self.description.strip():
            raise PlanningError("description is required")
        if self.status not in PLAN_STATUSES:
            raise PlanningError(f"Invalid plan item status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanItem":
        if not isinstance(data, dict):
            raise PlanningError("PlanItem data must be a dict")
        return cls(
            task_id=str(data.get("task_id") or ""),
            description=str(data.get("description") or ""),
            rationale=str(data.get("rationale") or ""),
            related_criteria=list(data.get("related_criteria") or []),
            dependencies=list(data.get("dependencies") or []),
            expected_files=list(data.get("expected_files") or []),
            verification_method=str(data.get("verification_method") or "inspection"),
            completion_conditions=list(data.get("completion_conditions") or []),
            risks=list(data.get("risks") or []),
            required=bool(data.get("required", True)),
            status=str(data.get("status") or PLAN_PENDING),
        )


@dataclass
class ImplementationPlan:
    project_id: str
    items: list[PlanItem] = field(default_factory=list)
    status: str = PLAN_PENDING
    created_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.project_id:
            raise PlanningError("project_id is required")
        if self.status not in PLAN_STATUSES:
            raise PlanningError(f"Invalid plan status: {self.status}")
        if not self.created_at:
            self.created_at = _utcnow()
        self._validate_graph()

    def _validate_graph(self) -> None:
        ids = [i.task_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise PlanningError("Duplicate task identifiers")
        known = set(ids)
        for item in self.items:
            for dep in item.dependencies:
                if dep not in known:
                    raise PlanningError(f"Unknown dependency: {dep}")
        # cycle detection
        graph = {i.task_id: list(i.dependencies) for i in self.items}
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                raise PlanningError("Circular dependency detected")
            if node in visited:
                return
            visiting.add(node)
            for dep in graph.get(node, []):
                dfs(dep)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            dfs(node)

    def ordered(self) -> list[PlanItem]:
        """Return items in dependency order (prerequisites first)."""
        by_id = {i.task_id: i for i in self.items}
        ordered: list[PlanItem] = []
        seen: set[str] = set()

        def visit(item: PlanItem) -> None:
            if item.task_id in seen:
                return
            for dep in item.dependencies:
                visit(by_id[dep])
            seen.add(item.task_id)
            ordered.append(item)

        for item in self.items:
            visit(item)
        return ordered

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "items": [i.to_dict() for i in self.items],
            "status": self.status,
            "created_at": self.created_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImplementationPlan":
        if not isinstance(data, dict):
            raise PlanningError("ImplementationPlan data must be a dict")
        items = [PlanItem.from_dict(x) for x in (data.get("items") or [])]
        return cls(
            project_id=str(data.get("project_id") or ""),
            items=items,
            status=str(data.get("status") or PLAN_PENDING),
            created_at=str(data.get("created_at") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass
class PlanningResult:
    plan: Optional[ImplementationPlan]
    success: bool
    error: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict() if self.plan else None,
            "success": self.success,
            "error": self.error,
            "notes": self.notes,
        }


def build_plan(
    spec: RequirementSpec,
    design: DesignDoc,
) -> PlanningResult:
    """Create an implementation plan. Does not execute anything."""
    if spec is None or design is None:
        return PlanningResult(
            plan=None, success=False, error="spec and design are required"
        )
    if spec.project_id != design.project_id:
        return PlanningResult(
            plan=None,
            success=False,
            error="project_id mismatch between requirements and design",
        )
    criterion_ids = [c.criterion_id for c in spec.acceptance_criteria]
    items = [
        PlanItem(
            task_id="req_review",
            description="Confirm requirements and assumptions",
            rationale="Planning starts from confirmed requirements",
            related_criteria=criterion_ids,
            verification_method="inspection",
            completion_conditions=["No unresolved critical questions"],
            required=True,
        ),
        PlanItem(
            task_id="implement_core",
            description="Implement functional requirements in the project workspace",
            rationale="Primary delivery",
            related_criteria=criterion_ids,
            dependencies=["req_review"],
            expected_files=["src/"],
            verification_method="unit_test",
            completion_conditions=["Core behavior matches criteria"],
            risks=["Out of scope for Phase 6C — do not generate code here"],
            required=True,
        ),
        PlanItem(
            task_id="write_tests",
            description="Add unit tests for acceptance criteria",
            rationale="Verification",
            related_criteria=criterion_ids,
            dependencies=["implement_core"],
            expected_files=["tests/"],
            verification_method="unit_test",
            completion_conditions=["Tests exist and are intended to be run later"],
            required=True,
        ),
        PlanItem(
            task_id="document",
            description="Document setup and limitations",
            rationale="Delivery clarity",
            related_criteria=criterion_ids[:1],
            dependencies=["write_tests"],
            expected_files=["README.md"],
            verification_method="inspection",
            completion_conditions=["Docs match implemented behavior"],
            required=True,
        ),
        PlanItem(
            task_id="optional_polish",
            description="Optional cleanup after required work",
            rationale="Non-blocking improvement",
            related_criteria=[],
            dependencies=["document"],
            required=False,
            status=PLAN_PENDING,
        ),
    ]
    try:
        plan = ImplementationPlan(
            project_id=spec.project_id,
            items=items,
            status=PLAN_READY,
            notes="Plan only. No code generation, install, or execution.",
        )
    except PlanningError as exc:
        return PlanningResult(plan=None, success=False, error=str(exc))

    return PlanningResult(
        plan=plan,
        success=True,
        notes="Plan produced. Status remains pending until later phases implement work.",
    )
