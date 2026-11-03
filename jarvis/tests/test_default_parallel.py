"""Prove default Orchestrator.run uses parallel waves."""

from __future__ import annotations

import threading
from typing import Any

from jarvis.core.agent_registry import AgentRegistry
from jarvis.core.agents.base import BaseAgent
from jarvis.core.models import AgentResult, TaskRecord
from jarvis.core.orchestrator import Orchestrator


class BarrierAgent(BaseAgent):
    name = "barrier"
    role = "Barrier"
    capabilities = ["barrier"]
    mode = "DETERMINISTIC"

    def __init__(self, gate: threading.Barrier, seen: list, label: str):
        self.gate = gate
        self.seen = seen
        self.label = label
        self.name = f"barrier_{label}"

    def can_handle(self, task: TaskRecord) -> bool:
        return True

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        self.gate.wait(timeout=3)
        self.seen.append(self.label)
        return AgentResult(success=True, outputs={"label": self.label}, mode=self.mode)


def test_default_run_parallel_overlap(tmp_path):
    gate = threading.Barrier(2)
    seen: list[str] = []
    registry = AgentRegistry()
    a = BarrierAgent(gate, seen, "a")
    b = BarrierAgent(gate, seen, "b")
    registry.register(a)
    registry.register(b)
    orch = Orchestrator(registry=registry, workspace=tmp_path)
    orch.concurrency_limit = 2
    t1 = TaskRecord.new(description="a", agent_name=a.name)
    t2 = TaskRecord.new(description="b", agent_name=b.name)
    result = orch.run("parallel pair", tasks=[t1, t2])
    assert result.status == "COMPLETED"
    assert len(seen) == 2
    assert orch._parallel_waves >= 1


def test_default_run_respects_dependencies(tmp_path):
    order: list[str] = []

    class OrderedAgent(BaseAgent):
        name = "ordered"
        role = "Ordered"
        capabilities = ["order"]
        mode = "DETERMINISTIC"

        def __init__(self, label: str):
            self.label = label
            self.name = f"ord_{label}"

        def can_handle(self, task: TaskRecord) -> bool:
            return True

        def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
            order.append(self.label)
            return AgentResult(success=True, outputs={}, mode=self.mode)

    registry = AgentRegistry()
    first = OrderedAgent("first")
    second = OrderedAgent("second")
    registry.register(first)
    registry.register(second)
    orch = Orchestrator(registry=registry, workspace=tmp_path)
    t1 = TaskRecord.new(description="first", agent_name=first.name)
    t2 = TaskRecord.new(description="second", agent_name=second.name, dependencies=[t1.task_id])
    result = orch.run("deps", tasks=[t1, t2])
    assert result.status == "COMPLETED"
    assert order == ["first", "second"]


def test_clarification_still_pauses(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    paused = orch.run("fix this", simple=True)
    assert paused.status == "WAITING"
    resumed = orch.resume(paused.run_id, "the store")
    assert "store" in resumed.objective
