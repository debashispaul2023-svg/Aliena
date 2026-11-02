"""Agent registration and lookup."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from .models import AgentResult, TaskRecord


class Agent(Protocol):
    name: str
    role: str
    capabilities: list[str]
    mode: str  # MOCKED | DETERMINISTIC | LIVE

    def can_handle(self, task: TaskRecord) -> bool: ...

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult: ...


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        if name not in self._agents:
            raise KeyError(f"Unknown agent: {name}")
        return self._agents[name]

    def has(self, name: str) -> bool:
        return name in self._agents

    def list_agents(self) -> list[str]:
        return sorted(self._agents.keys())

    def find_by_capability(self, capability: str) -> list[Agent]:
        return [a for a in self._agents.values() if capability in a.capabilities]

    def describe(self) -> list[dict[str, Any]]:
        out = []
        for a in self._agents.values():
            out.append(
                {
                    "name": a.name,
                    "role": a.role,
                    "capabilities": list(a.capabilities),
                    "mode": a.mode,
                }
            )
        return out
