"""Freelancer research hook. Drafts only; no submissions."""

from __future__ import annotations

from jarvis.integrations.agent_reach.detector import is_installed


def research_status() -> dict:
    return {
        "agent_reach": "installed" if is_installed() else "missing",
        "live_job_submit": "BLOCKED",
        "note": "Research adapter is optional. Jarvis continues without it.",
    }
