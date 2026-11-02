"""Agent roles. Draft and analyze only. No external actions."""

from __future__ import annotations

ROLES = [
    "job_research",
    "job_analysis",
    "proposal_writer",
    "pricing",
    "client_communication",
    "project_manager",
    "work_execution",
    "quality_review",
    "finance_analyst",
    "business_strategy",
]


def run_role(role: str, payload: dict) -> dict:
    if role not in ROLES:
        return {"ok": False, "error": "unknown_role"}
    if role == "proposal_writer":
        from jarvis.freelancer.proposals import draft_proposal
        return {"ok": True, "draft": draft_proposal(payload.get("job", {}), payload.get("profile", {}))}
    if role == "job_analysis":
        from jarvis.freelancer.jobs import analyze_job
        return {"ok": True, "analysis": analyze_job(payload.get("job", {}), payload.get("skills", []))}
    return {"ok": True, "role": role, "note": "Local draft only. No external action."}
