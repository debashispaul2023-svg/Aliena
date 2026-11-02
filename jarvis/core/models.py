"""Orchestrator task and result models."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Task lifecycle states
STATUS_PLANNED = "PLANNED"
STATUS_READY = "READY"
STATUS_RUNNING = "RUNNING"
STATUS_WAITING = "WAITING"
STATUS_RETRYING = "RETRYING"
STATUS_REVIEWING = "REVIEWING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
STATUS_CANCELLED = "CANCELLED"

VALID_STATUSES = {
    STATUS_PLANNED,
    STATUS_READY,
    STATUS_RUNNING,
    STATUS_WAITING,
    STATUS_RETRYING,
    STATUS_REVIEWING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_REQUIRES_APPROVAL,
    STATUS_CANCELLED,
}

# Allowed transitions
TRANSITIONS: dict[str, set[str]] = {
    STATUS_PLANNED: {STATUS_READY, STATUS_CANCELLED, STATUS_FAILED},
    STATUS_READY: {STATUS_RUNNING, STATUS_WAITING, STATUS_CANCELLED, STATUS_FAILED},
    STATUS_RUNNING: {
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_RETRYING,
        STATUS_WAITING,
        STATUS_REVIEWING,
        STATUS_REQUIRES_APPROVAL,
        STATUS_CANCELLED,
    },
    STATUS_WAITING: {STATUS_READY, STATUS_RUNNING, STATUS_CANCELLED, STATUS_FAILED},
    STATUS_RETRYING: {STATUS_RUNNING, STATUS_FAILED, STATUS_CANCELLED},
    STATUS_REVIEWING: {STATUS_COMPLETED, STATUS_FAILED, STATUS_REQUIRES_APPROVAL},
    STATUS_REQUIRES_APPROVAL: {STATUS_READY, STATUS_RUNNING, STATUS_CANCELLED, STATUS_FAILED},
    STATUS_COMPLETED: set(),
    STATUS_FAILED: {STATUS_RETRYING, STATUS_CANCELLED},
    STATUS_CANCELLED: set(),
}

TERMINAL = {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED}


@dataclass
class TaskRecord:
    task_id: str
    description: str
    objective: str = ""
    agent_name: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_PLANNED
    attempt_count: int = 0
    max_retries: int = 2
    error: Optional[str] = None
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    requires_approval: bool = False
    approved: bool = False
    cancelled: bool = False
    mode: str = "DETERMINISTIC"  # MOCKED | DETERMINISTIC | LIVE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def new(
        description: str,
        agent_name: Optional[str] = None,
        dependencies: Optional[list[str]] = None,
        inputs: Optional[dict[str, Any]] = None,
        objective: str = "",
        max_retries: int = 2,
        requires_approval: bool = False,
        mode: str = "DETERMINISTIC",
    ) -> "TaskRecord":
        now = utc_now()
        return TaskRecord(
            task_id=str(uuid.uuid4()),
            description=description,
            objective=objective or description,
            agent_name=agent_name,
            dependencies=list(dependencies or []),
            inputs=dict(inputs or {}),
            status=STATUS_PLANNED,
            max_retries=max_retries,
            created_at=now,
            updated_at=now,
            requires_approval=requires_approval,
            mode=mode,
        )


@dataclass
class AgentResult:
    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    mode: str = "DETERMINISTIC"
    notes: str = ""


@dataclass
class OrchestrationResult:
    run_id: str
    objective: str
    status: str  # COMPLETED | FAILED | CANCELLED | REQUIRES_APPROVAL
    tasks: list[TaskRecord] = field(default_factory=list)
    final_output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    experience_id: Optional[str] = None
    mode: str = "DETERMINISTIC"
    created_at: str = ""
    finished_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "objective": self.objective,
            "status": self.status,
            "tasks": [t.to_dict() for t in self.tasks],
            "final_output": self.final_output,
            "error": self.error,
            "experience_id": self.experience_id,
            "mode": self.mode,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }
