"""Sequential specialist orchestrator. Not fake parallel execution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    name: str
    role: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    error: str = ""


class DevOrchestrator:
    def plan(self, request: str) -> list[Task]:
        return [
            Task("understand", "architect"),
            Task("schema", "database", depends_on=["understand"]),
            Task("backend", "backend", depends_on=["schema"]),
            Task("frontend", "frontend", depends_on=["understand"]),
            Task("tests", "testing", depends_on=["backend", "frontend"]),
            Task("docs", "documentation", depends_on=["tests"]),
        ]

    def run(self, request: str, fail: str = "") -> list[Task]:
        tasks = {t.name: t for t in self.plan(request)}
        order = ["understand", "schema", "backend", "frontend", "tests", "docs"]
        for name in order:
            task = tasks[name]
            if any(tasks[dep].status != "done" for dep in task.depends_on):
                task.status = "blocked"
                task.error = "dependency failed"
                continue
            if fail and task.name == fail:
                task.status = "failed"
                task.error = "forced failure"
                continue
            task.status = "done"
        return [tasks[n] for n in order]
