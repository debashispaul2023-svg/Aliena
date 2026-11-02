"""Professional Development Engine foundations (Phase 6B).

Application-level workspace path boundaries only — not an OS sandbox.
"""

from .models import (
    AcceptanceCriterion,
    RequirementSpec,
    DesignDoc,
    ChangeSet,
    ModelValidationError,
    CRITERION_PENDING,
    CRITERION_PASS,
    CRITERION_FAIL,
    CRITERION_BLOCKED,
    CRITERION_SKIPPED,
    CHANGE_DRAFT,
    CHANGE_APPLIED,
    SPEC_DRAFT,
    SPEC_READY,
)
from .workspace import (
    WorkspaceManager,
    DevWorkspace,
    WorkspaceError,
    validate_project_name,
)

__all__ = [
    "AcceptanceCriterion",
    "RequirementSpec",
    "DesignDoc",
    "ChangeSet",
    "ModelValidationError",
    "CRITERION_PENDING",
    "CRITERION_PASS",
    "CRITERION_FAIL",
    "CRITERION_BLOCKED",
    "CRITERION_SKIPPED",
    "CHANGE_DRAFT",
    "CHANGE_APPLIED",
    "SPEC_DRAFT",
    "SPEC_READY",
    "WorkspaceManager",
    "DevWorkspace",
    "WorkspaceError",
    "validate_project_name",
]
