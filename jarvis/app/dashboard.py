"""Local status dashboard. No GUI required."""

from __future__ import annotations

from jarvis.integrations.agent_reach.detector import is_installed


def snapshot() -> dict:
    return {
        "gui": "BLOCKED_IN_THIS_WORKSPACE",
        "mcp": "NOT_CONNECTED",
        "agent_reach": "installed" if is_installed() else "missing",
        "generated_code_execution": "BLOCKED",
        "live_job_submit": "BLOCKED",
    }
