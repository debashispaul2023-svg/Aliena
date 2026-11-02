"""Proposal drafts. Never submits without approval."""

from __future__ import annotations

from typing import Any

from jarvis.freelancer.store import FreelancerStore


def draft_proposal(job: dict[str, Any], profile: dict[str, Any]) -> str:
    name = profile.get("name", "Freelancer")
    skills = ", ".join(profile.get("skills") or []) or "relevant skills"
    return (
        f"Hello,\n\n"
        f"I am {name}. I can help with: {job.get('title','this project')}.\n"
        f"Relevant skills: {skills}.\n"
        f"I will clarify requirements before starting and deliver on the agreed scope.\n\n"
        f"This is a draft. It has not been sent.\n"
    )


def suggest_bid(budget: str | None) -> str:
    if not budget:
        return "Ask the client for a budget range."
    return f"Start near the stated budget ({budget}) after clarifying scope."


def submit_proposal(store: FreelancerStore, proposal_id: int, *, approved: bool) -> dict[str, Any]:
    """Fail closed. Does not call any platform."""
    if not approved or not store.is_approved("submit_proposal", str(proposal_id)):
        store.audit("submit_blocked", str(proposal_id))
        return {"ok": False, "status": "BLOCKED", "reason": "approval_required"}
    return {
        "ok": False,
        "status": "BLOCKED",
        "reason": "no_platform_client",
        "note": "Approval recorded, but no live platform integration is configured.",
    }
