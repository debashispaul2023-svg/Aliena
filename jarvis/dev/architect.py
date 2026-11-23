"""Architecture planner. One shared contract for all agents."""

from __future__ import annotations

from jarvis.dev.task_understanding import TaskSpec


class ProjectArchitect:
    def plan(self, spec: TaskSpec) -> dict:
        return {
            "title": spec.title,
            "stack": {"frontend": "static html", "backend": "python stdlib", "database": "sqlite"},
            "folders": ["frontend", "backend", "database", "tests", "docs"],
            "api": ["/api/menu", "/api/contact"],
            "sequence": ["schema", "backend", "frontend", "tests", "docs"],
        }
