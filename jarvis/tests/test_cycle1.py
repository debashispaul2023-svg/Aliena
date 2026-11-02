"""Dashboard, approval center, circuit breaker."""

from __future__ import annotations

from jarvis.adapt.approval_center import ApprovalCenter
from jarvis.ai.circuit import CircuitBreaker
from jarvis.app.dashboard import snapshot


def test_dashboard_honest():
    data = snapshot()
    assert data["generated_code_execution"] == "BLOCKED"
    assert data["mcp"] == "NOT_CONNECTED"


def test_approval_fail_closed():
    center = ApprovalCenter()
    key = center.request("submit_proposal", "12")
    assert center.is_allowed(key) is False
    center.decide(key, True)
    assert center.is_allowed(key) is True


def test_circuit_opens():
    cb = CircuitBreaker(limit=2)
    assert cb.allow()
    cb.record_failure()
    cb.record_failure()
    assert cb.open
    cb.record_success()
    assert cb.allow()
