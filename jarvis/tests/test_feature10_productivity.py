"""Feature 10 focused tests. No live notifications."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.productivity.service import ProductivityService
from jarvis.productivity.storage import ProductivityStore


def test_task_and_priority(tmp_path: Path):
    store = ProductivityStore(tmp_path / "prod.db")
    svc = ProductivityService(store)
    project = svc.create_project("Aliena")
    task = svc.create_task("write docs", priority="HIGH", project_id=project, due_at="2020-01-01T00:00:00+00:00")
    svc.set_priority(task, "CRITICAL")
    overdue = svc.overdue("2026-01-01T00:00:00+00:00")
    assert overdue
    store.close()


def test_circular_dependency_rejected(tmp_path: Path):
    store = ProductivityStore(tmp_path / "prod.db")
    svc = ProductivityService(store)
    a = svc.create_task("a")
    b = svc.create_task("b")
    svc.depend(b, a)
    with pytest.raises(ValueError):
        svc.depend(a, b)
    store.close()


def test_reminder_not_claimed_delivered(tmp_path: Path):
    store = ProductivityStore(tmp_path / "prod.db")
    svc = ProductivityService(store)
    task = svc.create_task("remind me")
    first = svc.add_reminder(task, "2026-11-09T09:00:00+00:00")
    second = svc.add_reminder(task, "2026-11-09T09:00:00+00:00")
    assert first == second
    plan = svc.daily_plan()
    assert plan["notifications_delivered"] is False
    store.close()
