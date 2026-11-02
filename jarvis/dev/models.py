"""Core development-engine models (Phase 6B).

In-memory / serializable structures for requirements, design, and changes.
No database persistence in this phase.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Status constants (validated)
# ---------------------------------------------------------------------------

CRITERION_PENDING = "PENDING"
CRITERION_PASS = "PASS"
CRITERION_FAIL = "FAIL"
CRITERION_BLOCKED = "BLOCKED"
CRITERION_SKIPPED = "SKIPPED"

CRITERION_STATUSES = {
    CRITERION_PENDING,
    CRITERION_PASS,
    CRITERION_FAIL,
    CRITERION_BLOCKED,
    CRITERION_SKIPPED,
}

VERIFY_MANUAL = "manual"
VERIFY_UNIT_TEST = "unit_test"
VERIFY_INTEGRATION = "integration"
VERIFY_INSPECTION = "inspection"
VERIFY_OTHER = "other"

VERIFY_METHODS = {
    VERIFY_MANUAL,
    VERIFY_UNIT_TEST,
    VERIFY_INTEGRATION,
    VERIFY_INSPECTION,
    VERIFY_OTHER,
}

CHANGE_DRAFT = "DRAFT"
CHANGE_APPLIED = "APPLIED"
CHANGE_REVERTED = "REVERTED"
CHANGE_FAILED = "FAILED"

CHANGE_STATUSES = {
    CHANGE_DRAFT,
    CHANGE_APPLIED,
    CHANGE_REVERTED,
    CHANGE_FAILED,
}

SPEC_DRAFT = "DRAFT"
SPEC_READY = "READY"
SPEC_IN_PROGRESS = "IN_PROGRESS"
SPEC_DONE = "DONE"
SPEC_BLOCKED = "BLOCKED"

SPEC_STATUSES = {
    SPEC_DRAFT,
    SPEC_READY,
    SPEC_IN_PROGRESS,
    SPEC_DONE,
    SPEC_BLOCKED,
}


class ModelValidationError(ValueError):
    """Raised when model fields fail validation."""


def _require_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if value is None:
        raise ModelValidationError(f"{field_name} is required")
    if not isinstance(value, str):
        raise ModelValidationError(f"{field_name} must be a string")
    if not allow_empty and not value.strip():
        raise ModelValidationError(f"{field_name} must not be empty")
    return value


def _require_status(value: str, allowed: set[str], field_name: str = "status") -> str:
    if value not in allowed:
        raise ModelValidationError(
            f"Invalid {field_name}: {value!r}; allowed={sorted(allowed)}"
        )
    return value


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class AcceptanceCriterion:
    """A single measurable acceptance criterion."""

    description: str
    criterion_id: str = ""
    verification_method: str = VERIFY_INSPECTION
    required: bool = True
    status: str = CRITERION_PENDING
    evidence_ref: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        self.description = _require_str(self.description, "description")
        if not self.criterion_id:
            self.criterion_id = _new_id("ac_")
        self.verification_method = _require_status(
            self.verification_method, VERIFY_METHODS, "verification_method"
        )
        self.status = _require_status(self.status, CRITERION_STATUSES, "status")
        if self.evidence_ref is not None and not isinstance(self.evidence_ref, str):
            raise ModelValidationError("evidence_ref must be a string or None")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AcceptanceCriterion":
        if not isinstance(data, dict):
            raise ModelValidationError("AcceptanceCriterion data must be a dict")
        return cls(
            description=data.get("description", ""),
            criterion_id=data.get("criterion_id") or "",
            verification_method=data.get("verification_method", VERIFY_INSPECTION),
            required=bool(data.get("required", True)),
            status=data.get("status", CRITERION_PENDING),
            evidence_ref=data.get("evidence_ref"),
            notes=str(data.get("notes") or ""),
        )


@dataclass
class RequirementSpec:
    """Captured requirements for a development task/project."""

    user_request: str
    project_id: str = ""
    functional: list[str] = field(default_factory=list)
    non_functional: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    status: str = SPEC_DRAFT
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.user_request = _require_str(self.user_request, "user_request")
        if not self.project_id:
            self.project_id = _new_id("proj_")
        self.status = _require_status(self.status, SPEC_STATUSES, "status")
        now = _utcnow()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        # Normalize list fields
        for name in (
            "functional",
            "non_functional",
            "constraints",
            "assumptions",
            "clarifying_questions",
        ):
            val = getattr(self, name)
            if not isinstance(val, list):
                raise ModelValidationError(f"{name} must be a list")
            setattr(self, name, [str(x) for x in val])
        normalized: list[AcceptanceCriterion] = []
        for item in self.acceptance_criteria:
            if isinstance(item, AcceptanceCriterion):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(AcceptanceCriterion.from_dict(item))
            else:
                raise ModelValidationError(
                    "acceptance_criteria items must be AcceptanceCriterion or dict"
                )
        self.acceptance_criteria = normalized
        if not isinstance(self.metadata, dict):
            raise ModelValidationError("metadata must be a dict")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["acceptance_criteria"] = [c.to_dict() for c in self.acceptance_criteria]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RequirementSpec":
        if not isinstance(data, dict):
            raise ModelValidationError("RequirementSpec data must be a dict")
        criteria = data.get("acceptance_criteria") or []
        return cls(
            user_request=data.get("user_request", ""),
            project_id=data.get("project_id") or "",
            functional=list(data.get("functional") or []),
            non_functional=list(data.get("non_functional") or []),
            constraints=list(data.get("constraints") or []),
            assumptions=list(data.get("assumptions") or []),
            clarifying_questions=list(data.get("clarifying_questions") or []),
            acceptance_criteria=criteria,
            status=data.get("status", SPEC_DRAFT),
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class DesignDoc:
    """Architecture / design record for a project."""

    project_id: str
    overview: str = ""
    components: list[dict[str, Any]] = field(default_factory=list)
    data_flow: list[str] = field(default_factory=list)
    interfaces: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    trade_offs: list[str] = field(default_factory=list)
    security_considerations: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.project_id = _require_str(self.project_id, "project_id")
        self.overview = str(self.overview or "")
        now = _utcnow()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        for name in (
            "data_flow",
            "decisions",
            "trade_offs",
            "security_considerations",
            "limitations",
        ):
            val = getattr(self, name)
            if not isinstance(val, list):
                raise ModelValidationError(f"{name} must be a list")
            setattr(self, name, [str(x) for x in val])
        if not isinstance(self.components, list):
            raise ModelValidationError("components must be a list")
        if not isinstance(self.interfaces, list):
            raise ModelValidationError("interfaces must be a list")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesignDoc":
        if not isinstance(data, dict):
            raise ModelValidationError("DesignDoc data must be a dict")
        return cls(
            project_id=data.get("project_id", ""),
            overview=str(data.get("overview") or ""),
            components=list(data.get("components") or []),
            data_flow=list(data.get("data_flow") or []),
            interfaces=list(data.get("interfaces") or []),
            decisions=list(data.get("decisions") or []),
            trade_offs=list(data.get("trade_offs") or []),
            security_considerations=list(data.get("security_considerations") or []),
            limitations=list(data.get("limitations") or []),
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
        )


@dataclass
class ChangeSet:
    """Record of file changes for a project implementation step."""

    project_id: str
    changed_files: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    related_criteria: list[str] = field(default_factory=list)
    test_evidence: list[str] = field(default_factory=list)
    status: str = CHANGE_DRAFT
    change_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        self.project_id = _require_str(self.project_id, "project_id")
        if not self.change_id:
            self.change_id = _new_id("chg_")
        self.status = _require_status(self.status, CHANGE_STATUSES, "status")
        now = _utcnow()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        for name in ("changed_files", "summaries", "related_criteria", "test_evidence"):
            val = getattr(self, name)
            if not isinstance(val, list):
                raise ModelValidationError(f"{name} must be a list")
            setattr(self, name, [str(x) for x in val])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChangeSet":
        if not isinstance(data, dict):
            raise ModelValidationError("ChangeSet data must be a dict")
        return cls(
            project_id=data.get("project_id", ""),
            changed_files=list(data.get("changed_files") or []),
            summaries=list(data.get("summaries") or []),
            related_criteria=list(data.get("related_criteria") or []),
            test_evidence=list(data.get("test_evidence") or []),
            status=data.get("status", CHANGE_DRAFT),
            change_id=data.get("change_id") or "",
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
            notes=str(data.get("notes") or ""),
        )
