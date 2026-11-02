"""Unit tests for orchestrator core (graph, registry, transitions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.core.models import (
    TaskRecord,
    STATUS_PLANNED,
    STATUS_READY,
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_REQUIRES_APPROVAL,
)
from jarvis.core.task_graph import TaskGraph, CycleError, UnknownDependencyError
from jarvis.core.agent_registry import AgentRegistry
from jarvis.core.agents import build_default_agents
from jarvis.core.orchestrator import Orchestrator


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def orch(workspace: Path) -> Orchestrator:
    return Orchestrator(workspace=workspace)


def test_agents_registered(orch: Orchestrator) -> None:
    names = orch.registry.list_agents()
    for expected in (
        "planner",
        "researcher",
        "coder",
        "tester",
        "reviewer",
        "documentation",
        "architect",
        "debugger",
        "prompt_engineer",
        "project_manager",
        "resource_finder",
    ):
        assert expected in names


def test_unknown_agent_fails(orch: Orchestrator) -> None:
    t = TaskRecord.new("ghost", agent_name="does_not_exist")
    result = orch.run("unknown agent", tasks=[t], record_experience=False)
    assert result.status == STATUS_FAILED
    assert "Unknown agent" in (result.tasks[0].error or "")


def test_cycle_rejected(orch: Orchestrator) -> None:
    a = TaskRecord.new("A", agent_name="planner")
    b = TaskRecord.new("B", agent_name="planner", dependencies=[a.task_id])
    a.dependencies = [b.task_id]
    result = orch.run("cycle", tasks=[a, b], record_experience=False)
    assert result.status == STATUS_FAILED
    assert "cycle" in (result.error or "").lower()


def test_unknown_dependency_rejected(orch: Orchestrator) -> None:
    t = TaskRecord.new("x", agent_name="planner", dependencies=["missing-id"])
    result = orch.run("bad dep", tasks=[t], record_experience=False)
    assert result.status == STATUS_FAILED
    assert "unknown" in (result.error or "").lower()


def test_invalid_transition_raises(orch: Orchestrator) -> None:
    t = TaskRecord.new("x", agent_name="planner")
    with pytest.raises(ValueError):
        orch.transition(t, STATUS_COMPLETED)  # PLANNED cannot jump to COMPLETED


def test_simple_success(orch: Orchestrator, workspace: Path) -> None:
    result = orch.run("write hello", simple=True, content="hello world\n", record_experience=False)
    assert result.status == STATUS_COMPLETED
    assert (workspace / "artifact.txt").exists()
    assert "hello world" in (workspace / "artifact.txt").read_text()


def test_retry_then_success(orch: Orchestrator) -> None:
    result = orch.run(
        "retry demo",
        simple=True,
        force_fail=True,
        fail_until_attempt=2,
        content="after retry\n",
        record_experience=False,
    )
    coder = next(t for t in result.tasks if t.agent_name == "coder")
    assert coder.attempt_count >= 2
    assert result.status == STATUS_COMPLETED


def test_retry_exhausted_fails(orch: Orchestrator) -> None:
    result = orch.run(
        "always fail",
        simple=True,
        force_fail=True,
        fail_until_attempt=99,
        record_experience=False,
    )
    assert result.status == STATUS_FAILED
    coder = next(t for t in result.tasks if t.agent_name == "coder")
    assert coder.status == STATUS_FAILED
    assert coder.attempt_count == coder.max_retries + 1


def test_cancellation(orch: Orchestrator) -> None:
    # Pre-create a run then cancel mid-way by flagging before run finishes —
    # cancel_run on a completed run still marks; test cancel API.
    result = orch.run("cancellable", simple=True, content="x\n", record_experience=False)
    # cancel after completion is no-op on terminal tasks but returns True
    assert orch.cancel_run(result.run_id) is True


def test_approval_blocks(orch: Orchestrator) -> None:
    result = orch.run(
        "needs approval",
        simple=True,
        requires_approval=True,
        content="secret work\n",
        record_experience=False,
    )
    assert result.status == STATUS_REQUIRES_APPROVAL
    # artifact should not exist yet because coder was blocked
    # (planner may have completed; coder requires approval)
    coder = next(t for t in result.tasks if t.agent_name == "coder")
    assert coder.status == STATUS_REQUIRES_APPROVAL


def test_multi_step_order(orch: Orchestrator, workspace: Path) -> None:
    result = orch.run("full pipeline", simple=False, content="pipeline\n", record_experience=False)
    assert result.status == STATUS_COMPLETED
    # topological: planner before researcher before architect before coder...
    order = {t.agent_name: i for i, t in enumerate(result.tasks)}
    assert order["planner"] < order["researcher"] < order["architect"] < order["coder"]
    assert order["coder"] < order["tester"] < order["reviewer"] < order["documentation"]
    assert (workspace / "artifact.txt").exists()
    assert (workspace / "ORCHESTRATION_NOTES.md").exists()


def test_path_traversal_rejected(orch: Orchestrator) -> None:
    t = TaskRecord.new(
        "evil",
        agent_name="coder",
        inputs={"filename": "../escape.txt", "content": "nope", "workspace": str(orch.workspace)},
    )
    result = orch.run("evil path", tasks=[t], record_experience=False)
    assert result.status == STATUS_FAILED
