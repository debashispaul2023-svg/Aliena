"""Skill and experience data models for Jarvis."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Lifecycle statuses
STATUS_PROPOSED = "PROPOSED"
STATUS_VALIDATING = "VALIDATING"
STATUS_VERIFIED = "VERIFIED"
STATUS_ACTIVE = "ACTIVE"
STATUS_REJECTED = "REJECTED"

VALID_STATUSES = {
    STATUS_PROPOSED,
    STATUS_VALIDATING,
    STATUS_VERIFIED,
    STATUS_ACTIVE,
    STATUS_REJECTED,
}

# Allowed transitions (from → set of allowed next)
LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    STATUS_PROPOSED: {STATUS_VALIDATING, STATUS_REJECTED},
    STATUS_VALIDATING: {STATUS_VERIFIED, STATUS_REJECTED, STATUS_PROPOSED},
    STATUS_VERIFIED: {STATUS_ACTIVE, STATUS_REJECTED, STATUS_PROPOSED},
    STATUS_ACTIVE: {STATUS_VERIFIED, STATUS_REJECTED},  # deactivate → VERIFIED
    STATUS_REJECTED: {STATUS_PROPOSED},  # can re-propose after edits
}


@dataclass
class Skill:
    skill_id: str
    name: str
    description: str
    category: str = "general"
    when_to_use: str = ""
    prerequisites: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    procedure: list[dict[str, Any]] = field(default_factory=list)
    # procedure steps are structured dicts, e.g. {"step": 1, "action": "...", "tool": "..."}
    examples: list[str] = field(default_factory=list)
    known_failures: list[str] = field(default_factory=list)
    successful_patterns: list[str] = field(default_factory=list)
    validation_tests: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    version: int = 1
    source_task: Optional[str] = None
    status: str = STATUS_PROPOSED
    created_at: str = ""
    updated_at: str = ""
    usage_count: int = 0
    parent_skill_id: Optional[str] = None  # links version lineage
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class Experience:
    experience_id: str
    task_id: str
    objective: str
    task_plan: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    agents_used: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    test_results: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "unknown"  # success | failure | partial | unknown
    notes: str = ""
    created_at: str = ""
    completed_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Experience":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
