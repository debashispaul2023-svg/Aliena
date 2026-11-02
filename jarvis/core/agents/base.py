"""Base agent helpers."""

from __future__ import annotations

from typing import Any

from jarvis.core.models import AgentResult, TaskRecord


class BaseAgent:
    name: str = "base"
    role: str = "base"
    capabilities: list[str] = []
    mode: str = "DETERMINISTIC"

    def can_handle(self, task: TaskRecord) -> bool:
        return task.agent_name == self.name

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        raise NotImplementedError
