"""Workflows A-F through the real orchestrator."""

from __future__ import annotations

import threading

from jarvis.core.orchestrator import Orchestrator
from jarvis.core.parallel import run_independent
from jarvis.core.models import TaskRecord
from jarvis.memory.store import MemoryStore, CATEGORY_PROJECT


def test_parallel_barrier_overlap():
    gate = threading.Barrier(2)
    seen = []

    def worker(task):
        gate.wait(timeout=2)
        seen.append(task.task_id)
        return {"id": task.task_id}

    a = TaskRecord.new(description="a", agent_name="researcher")
    b = TaskRecord.new(description="b", agent_name="researcher")
    out = run_independent([a, b], worker, limit=2)
    assert len(out) == 2
    assert len(seen) == 2


def test_workflow_d_clarification(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    paused = orch.run("fix this", simple=True)
    assert paused.status == "WAITING"
    resumed = orch.resume(paused.run_id, "the memory store")
    assert resumed.run_id != paused.run_id
    assert "memory store" in resumed.objective


def test_workflow_conflict(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    result = orch.escalate_conflict([
        {"agent": "a", "claim": "yes"},
        {"agent": "b", "claim": "no"},
    ])
    assert result["status"] == "CONFLICT"


def test_workflow_b_full_plan(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    tasks = orch.plan_simple("research notes", simple=False)
    names = [t.agent_name for t in tasks]
    assert names[:4] == ["planner", "researcher", "architect", "coder"]


def test_workflow_f_memory(tmp_path):
    db = tmp_path / "mem.db"
    store = MemoryStore(db)
    store.save("Project uses SQLite", category=CATEGORY_PROJECT, project_id="jarvis")
    orch = Orchestrator(workspace=tmp_path, memory_store=store)
    orch.run("project sqlite", simple=True)
    store.close()
    again = MemoryStore(db)
    assert again.search("SQLite", project_id="jarvis")
    again.close()
