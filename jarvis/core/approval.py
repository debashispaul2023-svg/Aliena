"""Shared approval record (additive; no existing module is changed to use it).

``ApprovalDecision`` is a small immutable record that every module *may* use to
express "was this exact action approved?". It exists so Part B can wrap its own
approval objects without importing Part A internals, and so Part A has one
fail-closed way to check them.

Fail-closed rules
-----------------
* Unknown / missing / malformed input -> ``approved=False``.
* An approval is bound to an ``action`` and, when supplied, a ``fingerprint``.
  ``allows(action, fingerprint)`` is True only if *both* match.
* If a fingerprint was recorded, a caller that supplies none is refused.
* Records carry identifiers only - never payloads, file contents or secrets.
  ``reason`` is passed through the shared redactor.

Adapters use *duck typing* (attribute names only) so this module imports
nothing from Part B or from ``jarvis/adapt``.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.core.constants import APPROVAL_REQUIRED
from jarvis.core.redaction import redact_secrets


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ApprovalDecision:
    action: str
    approved: bool = False
    reviewer: str = ""
    fingerprint: Optional[str] = None
    target: Optional[str] = None
    reason: str = ""
    decided_at: str = ""
    source: str = "shared"

    def allows(self, action: str, fingerprint: Optional[str] = None) -> bool:
        """True only for an explicit approval of this exact action (and fingerprint)."""
        if self.approved is not True:
            return False
        if not self.action or self.action != action:
            return False
        if self.fingerprint is not None:
            return fingerprint is not None and fingerprint == self.fingerprint
        return True

    @property
    def status(self) -> str:
        """``"APPROVED"`` or the fail-closed ``APPROVAL_REQUIRED`` string."""
        return "APPROVED" if self.approved is True else APPROVAL_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def deny(action: str, reason: str = "", *, source: str = "shared") -> ApprovalDecision:
    """Explicit negative decision (the default state of any request)."""
    return ApprovalDecision(
        action=str(action or ""),
        approved=False,
        reason=redact_secrets(reason),
        decided_at=_now(),
        source=source,
    )


def approve(
    action: str,
    *,
    reviewer: str,
    fingerprint: Optional[str] = None,
    target: Optional[str] = None,
    reason: str = "",
    source: str = "shared",
) -> ApprovalDecision:
    """Positive decision. A non-empty reviewer is required, otherwise it is a denial."""
    if not action or not str(reviewer or "").strip():
        return deny(action, "missing action or reviewer", source=source)
    return ApprovalDecision(
        action=str(action),
        approved=True,
        reviewer=str(reviewer).strip(),
        fingerprint=fingerprint,
        target=target,
        reason=redact_secrets(reason),
        decided_at=_now(),
        source=source,
    )


# --------------------------------------------------------------------------- adapters
# Each adapter reads attributes only and returns a denial for anything unexpected.


def from_draft_approval(approval: Any, *, action: str = "apply_draft") -> ApprovalDecision:
    """``jarvis.dev.drafts.DraftApproval`` (draft_id, fingerprint, reviewer)."""
    try:
        fp = getattr(approval, "fingerprint", None)
        reviewer = getattr(approval, "reviewer", "")
        if not fp:
            return deny(action, "no fingerprint", source="dev.drafts")
        return approve(
            action,
            reviewer=reviewer,
            fingerprint=fp,
            target=getattr(approval, "draft_id", None),
            source="dev.drafts",
        )
    except Exception:
        return deny(action, "unreadable approval", source="dev.drafts")


def from_execution_approval(approval: Any, *, action: str = "execute_artifact") -> ApprovalDecision:
    """``jarvis.dev.execution_backend.Approval`` (manifest_fingerprint, backend, approved)."""
    try:
        if getattr(approval, "approved", False) is not True:
            return deny(action, "not approved", source="dev.execution_backend")
        return approve(
            action,
            reviewer="execution_approval",
            fingerprint=getattr(approval, "manifest_fingerprint", None),
            target=getattr(approval, "backend", None),
            source="dev.execution_backend",
        )
    except Exception:
        return deny(action, "unreadable approval", source="dev.execution_backend")


def from_record(record: Any) -> ApprovalDecision:
    """Generic record with ``action``, ``approved`` and ``reviewer`` attributes.

    Matches Part B ``desktop.approval.ApprovalRecord`` without importing it.
    Note: such records have no fingerprint, so the resulting decision is bound
    to the action name only.
    """
    try:
        action = getattr(record, "action", "")
        if getattr(record, "approved", False) is not True:
            return deny(action, "not approved", source="record")
        return approve(
            action,
            reviewer=getattr(record, "reviewer", ""),
            target=getattr(record, "approval_id", None),
            source="record",
        )
    except Exception:
        return deny("", "unreadable record", source="record")


def from_confirmation(action: str, target_id: str, user_confirmed: bool, *, reviewer: str = "user") -> ApprovalDecision:
    """Shape used by Part B freelancer approvals: (action, target_id, user_confirmed)."""
    if user_confirmed is not True:
        return deny(action, "not confirmed", source="confirmation")
    return approve(action, reviewer=reviewer, target=target_id, source="confirmation")


__all__ = [
    "ApprovalDecision",
    "approve",
    "deny",
    "from_draft_approval",
    "from_execution_approval",
    "from_record",
    "from_confirmation",
]
