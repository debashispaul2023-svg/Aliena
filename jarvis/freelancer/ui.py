"""Local dashboard sections for the Freelancer engine.

Does not launch a GUI. Safe to import without PyQt.
"""

from __future__ import annotations

SECTIONS = [
    "Dashboard",
    "Job Finder",
    "Job Analysis",
    "Proposals",
    "Profile & Portfolio",
    "Client Manager",
    "Project Manager",
    "Work Assistant",
    "Finance",
    "Digital Products",
    "Affiliate Marketing",
    "Content Business",
    "Learning Center",
    "Automation",
    "Analytics",
    "Settings & Permissions",
]


def dashboard(store) -> dict:
    jobs = store.list_jobs()
    return {
        "sections": list(SECTIONS),
        "jobs": len(jobs),
        "income_total": store.income_total(),
        "live_platforms": "BLOCKED",
    }
