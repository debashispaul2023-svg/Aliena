"""Freelancer status helpers. External actions stay approval-gated."""

from __future__ import annotations

from jarvis.freelancer.approval import requires_approval


def external_action_status(action: str, confirmed: bool) -> dict:
    if requires_approval(action) and not confirmed:
        return {"ok": False, "status": "APPROVAL_REQUIRED", "submitted": False}
    if requires_approval(action):
        return {"ok": True, "status": "APPROVED_NOT_SUBMITTED", "submitted": False}
    return {"ok": True, "status": "LOCAL_ONLY", "submitted": False}
