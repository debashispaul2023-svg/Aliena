"""Adapter registering the Creator Engine as an agent in Aliena's existing orchestrator registry."""

from __future__ import annotations

from typing import Any, Optional

from jarvis.core.agents.base import BaseAgent
from jarvis.core.models import AgentResult, TaskRecord
from jarvis.creator.engine import CreatorEngine


class CreatorAgent(BaseAgent):
    name = "creator"
    role = "Universal project creator (plan, generate, statically verify, package)"
    capabilities = ["create_project", "website", "backend", "python_app", "mobile_scaffold", "game_scaffold"]
    mode = "DETERMINISTIC"

    def __init__(self, engine: Optional[CreatorEngine] = None) -> None:
        self.engine = engine

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        engine = self.engine or context.get("creator_engine")
        if engine is None:
            return AgentResult(False, error="no CreatorEngine configured", mode=self.mode)
        request = (task.inputs or {}).get("request") or task.description
        if not isinstance(request, str) or not request.strip():
            return AgentResult(False, error="task has no request text", mode=self.mode)
        res = engine.create(request, project_name=task.inputs.get("project_name"), spec=task.inputs.get("spec"),
                            composer_id=task.inputs.get("composer_id"), auto_package=bool(task.inputs.get("auto_package", True)))
        ok = res.status in ("delivered", "static_verified")
        out = {k: v for k, v in res.to_dict().items() if k not in ("files", "stages")}
        out["file_count"] = len(res.files)
        return AgentResult(ok, outputs=out, error=None if ok else (res.error or res.message), mode=self.mode, notes=res.message)


def register_creator_agent(registry: Any, engine: CreatorEngine) -> CreatorAgent:
    agent = CreatorAgent(engine)
    registry.register(agent)
    return agent
