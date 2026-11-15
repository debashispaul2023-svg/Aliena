"""Productivity service. No live notifications and no Gemini calls."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from jarvis.productivity.storage import ProductivityStore

PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


class ProductivityService:
    def __init__(self, store: ProductivityStore) -> None:
        self.store = store

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_project(self, name: str, deadline: str | None = None) -> int:
        if not name.strip():
            raise ValueError("project name required")
        return self.store.add_project(name.strip(), deadline, self._now())

    def create_task(self, title: str, *, description: str = "", priority: str = "MEDIUM", category: str = "", project_id: Optional[int] = None, due_at: str | None = None) -> int:
        if not title.strip():
            raise ValueError("title required")
        if priority not in PRIORITIES:
            raise ValueError("invalid priority")
        task_id = self.store.add_task(title.strip(), description, priority, category, project_id, due_at, self._now())
        self.store.history(task_id, "create", title, self._now())
        return task_id

    def complete_task(self, task_id: int) -> None:
        self.store.update_task(task_id, status="done", updated_at=self._now())
        self.store.history(task_id, "complete", "done", self._now())

    def set_priority(self, task_id: int, priority: str) -> None:
        if priority not in PRIORITIES:
            raise ValueError("invalid priority")
        self.store.update_task(task_id, priority=priority, updated_at=self._now())
        self.store.history(task_id, "priority", priority, self._now())

    def list_tasks(self, *, status: str = "", project_id: Optional[int] = None) -> list[dict]:
        return self.store.list_tasks(status=status, project_id=project_id)

    def overdue(self, now: str | None = None) -> list[dict]:
        current = now or self._now()
        return [t for t in self.store.list_tasks(status="pending") if t.get("due_at") and t["due_at"] < current]

    def add_reminder(self, task_id: int, remind_at: str) -> int:
        return self.store.add_reminder(task_id, remind_at, self._now())

    def depend(self, task_id: int, depends_on: int) -> None:
        self.store.add_dependency(task_id, depends_on)

    def project_progress(self, project_id: int) -> dict:
        tasks = self.store.list_tasks(project_id=project_id)
        done = sum(1 for t in tasks if t["status"] == "done")
        total = len(tasks)
        return {"total": total, "done": done, "percent": (done / total * 100) if total else 0}

    def daily_plan(self, now: str | None = None) -> dict:
        current = now or self._now()
        pending = self.store.list_tasks(status="pending")
        return {
            "pending": pending,
            "overdue": [t for t in pending if t.get("due_at") and t["due_at"] < current],
            "notifications_delivered": False,
        }
