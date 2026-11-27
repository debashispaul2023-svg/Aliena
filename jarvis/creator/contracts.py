"""Typed contracts for the Creator Engine (C1). Agents exchange only these."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class ProjectType(str, Enum):
    STATIC_WEBSITE = "static_website"
    REACT_APP = "react_app"
    NEXTJS_APP = "nextjs_app"
    PYTHON_APP = "python_app"
    FASTAPI_BACKEND = "fastapi_backend"
    DATABASE_PROJECT = "database_project"
    DESKTOP_APP = "desktop_app"
    MOBILE_SCAFFOLD = "mobile_scaffold"
    GAME_SCAFFOLD = "game_scaffold"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


class CreatorPhase(str, Enum):
    PLAN = "plan"
    GENERATE = "generate"
    VALIDATE = "validate"
    TEST = "test"
    DIAGNOSE = "diagnose"
    CORRECT = "correct"
    RETEST = "retest"
    DELIVER = "deliver"


class Permission(str, Enum):
    READ_PROJECT = "read_project"
    WRITE_NEW_WORKSPACE = "write_new_workspace"
    STATIC_ANALYSIS = "static_analysis"
    PROPOSE_ONLY = "propose_only"
    EXECUTE_CODE = "execute_code"          # never granted in C1
    NETWORK = "network"                    # never granted in C1
    INSTALL_DEPENDENCIES = "install_dependencies"  # approval-gated


class TaskStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    responsibility: str
    permissions: frozenset
    timeout_seconds: int = 30
    input_keys: tuple = ()
    output_keys: tuple = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["permissions"] = sorted(p.value for p in self.permissions)
        return d


@dataclass
class TaskContract:
    task_id: str
    project_id: str
    agent: str
    phase: CreatorPhase
    inputs: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30

    def validate(self, spec: AgentSpec) -> None:
        if not self.task_id or not self.project_id:
            raise ContractError("task_id and project_id are required")
        if self.agent != spec.name:
            raise ContractError("contract addressed to a different agent")
        missing = [k for k in spec.input_keys if k not in self.inputs]
        if missing:
            raise ContractError(f"missing inputs: {missing}")
        if self.timeout_seconds <= 0 or self.timeout_seconds > spec.timeout_seconds:
            raise ContractError("timeout outside agent limit")


@dataclass
class TaskResult:
    task_id: str
    agent: str
    status: TaskStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    mock: bool = True  # offline heuristic output; never presented as live AI

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class StackSelection:
    project_type: ProjectType
    languages: list[str]
    frameworks: list[str]
    folders: list[str]
    generator_available: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["project_type"] = self.project_type.value
        return d


@dataclass
class CreatorPlan:
    project_id: str
    project_type: ProjectType
    stack: StackSelection
    phases: list[str]
    agent_tasks: list[dict[str, Any]]
    requirements: dict[str, Any]
    design: dict[str, Any]
    implementation_plan: dict[str, Any]
    approvals_required: list[str]
    warnings: list[str] = field(default_factory=list)
    mock: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_type": self.project_type.value,
            "stack": self.stack.to_dict(),
            "phases": list(self.phases),
            "agent_tasks": list(self.agent_tasks),
            "requirements": self.requirements,
            "design": self.design,
            "implementation_plan": self.implementation_plan,
            "approvals_required": list(self.approvals_required),
            "warnings": list(self.warnings),
            "mock": self.mock,
        }
