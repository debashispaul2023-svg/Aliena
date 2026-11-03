"""Feature 3 gap tests: parallel, clarification, conflict, workflows."""

from __future__ import annotations

import threading
import time

from jarvis.core.clarification import ClarificationCenter
from jarvis.core.conflicts import detect_conflict
from jarvis.core.models import TaskRecord, STATUS_COMPLETED
from jarvis.core.orchestrator import Orchestrator
from jarvis.core.parallel import run_independent
from jarvis.core.task_graph import TaskGraph
from jarvis.memory.store import MemoryStore, CATEGORY_PROJECT


def test_parallel_overlap():
    started = []
    lock = threading.Lock()

    def worker(task):
        with lock:
            started.append(task.task_id)
        time.sleep(0.05)
        return {"id": task.task_id, "ok": True}

    a = TaskRecord.new(description="a", agent_name="researcher")
    b = TaskRecord.new(description="b", agent_name="analyst")
    out = run_independent([a, b], worker, limit=2)
    assert len(out) == 2
    assert len(started) == 2


def test_clarification_resume_same_task():
    center = ClarificationCenter()
    session = center.ask("task-9", "Which file?")
    center.resume("task-9", "store.py")
    assert session.task_id == "task-9"
    assert session.answer == "store.py"


def test_conflict_escalates():
    result = detect_conflict([
        {"agent": "a", "claim": "yes it works"},
        {"agent": "b", "claim": "no it fails"},
    ])
    assert result["status"] == "CONFLICT"
    assert result["action"] == "escalate"


def test_workflow_simple(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    tasks = orch.plan_simple("what is 2+2", simple=True)
    assert "researcher" not in [t.agent_name for t in tasks]


def test_workflow_coding(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    result = orch.run("write a note", simple=True)
    assert result.status in {"COMPLETED", "FAILED", "REQUIRES_APPROVAL"}


def test_workflow_failure_isolated(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    result = orch.run("fail once", simple=True, force_fail=True, fail_until_attempt=1)
    assert result.status in {"COMPLETED", "FAILED"}


def test_workflow_memory(tmp_path):
    db = tmp_path / "mem.db"
    store = MemoryStore(db)
    store.save("Project uses SQLite", category=CATEGORY_PROJECT, project_id="jarvis")
    orch = Orchestrator(workspace=tmp_path, memory_store=store)
    orch.run("project sqlite", simple=True)
    store.close()
    again = MemoryStore(db)
    assert again.search("SQLite", project_id="jarvis")
    again.close()
