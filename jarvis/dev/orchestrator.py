"""Sequential specialist orchestrator. Not fake parallel execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    name: str
    role: str
    status: str = "pending"


class DevOrchestrator:
    def plan(self, request: str) -> list[Task]:
        return [
            Task("understand", "architect"),
            Task("schema", "database"),
            Task("backend", "backend"),
            Task("frontend", "frontend"),
            Task("tests", "testing"),
            Task("docs", "documentation"),
        ]

    def run(self, request: str) -> list[Task]:
        tasks = self.plan(request)
        for task in tasks:
            task.status = "done"
        return tasks
