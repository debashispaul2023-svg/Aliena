"""Freelancer engine tests. No live platform calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.freelancer.approval import approve, requires_approval
from jarvis.freelancer.finance import platform_fee, record_income
from jarvis.freelancer.jobs import analyze_job
from jarvis.freelancer.proposals import draft_proposal, submit_proposal
from jarvis.freelancer.store import FreelancerStore
from jarvis.freelancer.ui import dashboard


@pytest.fixture
def store(tmp_path: Path):
    return FreelancerStore(tmp_path / "freelancer.db")


def test_job_and_analysis(store):
    jid = store.add_job(
        platform="manual",
        title="Python automation",
        description="Build a Python script. No upfront payment.",
        budget="100 USD",
    )
    assert jid
    analysis = analyze_job(
        {"title": "Python automation", "description": "Build a Python script"},
        ["python"],
    )
    assert "python" in analysis["matched_skills"]
    assert analysis["suitability_score"] > 0


def test_scam_flag(store):
    analysis = analyze_job(
        {"title": "Quick job", "description": "Pay upfront via gift card"},
        ["python"],
    )
    assert analysis["risks"]


def test_proposal_requires_approval(store):
    jid = store.add_job(title="Logo", description="Design a logo")
    body = draft_proposal({"title": "Logo"}, {"name": "Ada", "skills": ["design"]})
    pid = store.add_proposal(jid, body, "50")
    blocked = submit_proposal(store, pid, approved=False)
    assert blocked["status"] == "BLOCKED"
    assert requires_approval("submit_proposal")
    approve(store, "submit_proposal", str(pid), True)
    still = submit_proposal(store, pid, approved=True)
    assert still["reason"] == "no_platform_client"


def test_finance(store):
    record_income(store, "logo", 80)
    assert store.income_total() == 80
    assert platform_fee(80, 0.2) == 16


def test_dashboard(store):
    store.add_job(title="A", description="B")
    d = dashboard(store)
    assert d["jobs"] == 1
    assert "Finance" in d["sections"]
    assert d["live_platforms"] == "BLOCKED"
