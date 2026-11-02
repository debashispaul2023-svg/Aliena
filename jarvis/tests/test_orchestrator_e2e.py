"""End-to-end orchestrator scenarios A–L (mandatory)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.core.orchestrator import Orchestrator
from jarvis.core.models import (
    TaskRecord,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_REQUIRES_APPROVAL,
    STATUS_CANCELLED,
)
from jarvis.skills import SkillRegistry, ExperienceStore, LearningPipeline
from jarvis.memory import MemoryStore


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "orch_ws"


@pytest.fixture
def stores(tmp_path: Path):
    skills_db = tmp_path / "skills.db"
    mem_db = tmp_path / "mem.db"
    reg = SkillRegistry(skills_db)
    exp = ExperienceStore(skills_db)
    mem = MemoryStore(mem_db)
    pipe = LearningPipeline(reg, exp)
    return reg, exp, mem, pipe


@pytest.fixture
def orch(workspace: Path, stores) -> Orchestrator:
    reg, exp, mem, pipe = stores
    return Orchestrator(
        workspace=workspace,
        skill_registry=reg,
        memory_store=mem,
        experience_store=exp,
        learning_pipeline=pipe,
    )


def test_a_simple_task(orch: Orchestrator, workspace: Path) -> None:
    r = orch.run("simple hello", simple=True, content="hello\n")
    assert r.status == STATUS_COMPLETED
    assert (workspace / "artifact.txt").read_text() == "hello\n"


def test_b_multi_step_task(orch: Orchestrator, workspace: Path) -> None:
    r = orch.run("multi step build", simple=False, content="built\n")
    assert r.status == STATUS_COMPLETED
    assert len(r.tasks) >= 5
    assert (workspace / "artifact.txt").exists()
    assert (workspace / "ORCHESTRATION_NOTES.md").exists()


def test_c_independent_tasks(orch: Orchestrator) -> None:
    a = TaskRecord.new("indep-a", agent_name="planner", inputs={"objective": "A", "simple": True})
    b = TaskRecord.new("indep-b", agent_name="planner", inputs={"objective": "B", "simple": True})
    r = orch.run("independent", tasks=[a, b], record_experience=False)
    assert r.status == STATUS_COMPLETED
    assert all(t.status == STATUS_COMPLETED for t in r.tasks)


def test_d_dependency_cycle(orch: Orchestrator) -> None:
    a = TaskRecord.new("A", agent_name="planner")
    b = TaskRecord.new("B", agent_name="planner", dependencies=[a.task_id])
    a.dependencies = [b.task_id]
    r = orch.run("cycle", tasks=[a, b], record_experience=False)
    assert r.status == STATUS_FAILED
    assert "cycle" in (r.error or "").lower()


def test_e_agent_failure(orch: Orchestrator) -> None:
    r = orch.run(
        "will fail",
        simple=True,
        force_fail=True,
        fail_until_attempt=99,
        record_experience=False,
    )
    assert r.status == STATUS_FAILED
    assert any(t.status == STATUS_FAILED for t in r.tasks)


def test_f_retry(orch: Orchestrator) -> None:
    r = orch.run(
        "retry ok",
        simple=True,
        force_fail=True,
        fail_until_attempt=2,
        content="ok\n",
        record_experience=False,
    )
    assert r.status == STATUS_COMPLETED
    coder = next(t for t in r.tasks if t.agent_name == "coder")
    assert coder.attempt_count >= 2


def test_g_cancellation(orch: Orchestrator) -> None:
    # Run completes then cancel API exercised; for mid-run cancel, set flag via custom path
    r = orch.run("cancel me", simple=True, content="x\n", record_experience=False)
    assert orch.cancel_run(r.run_id) is True
    loaded = orch.get_run(r.run_id)
    assert loaded is not None


def test_h_unknown_agent(orch: Orchestrator) -> None:
    t = TaskRecord.new("x", agent_name="nope")
    r = orch.run("unknown", tasks=[t], record_experience=False)
    assert r.status == STATUS_FAILED
    assert "Unknown agent" in (r.tasks[0].error or "")


def test_i_memory_and_skill_integration(orch: Orchestrator, stores) -> None:
    reg, exp, mem, pipe = stores
    mem.save("User prefers concise reports", category="preference")
    # seed a skill
    s = reg.create_skill(
        name="concise_report",
        when_to_use="write concise reports",
        procedure=[{"step": 1, "action": "summarize"}],
    )
    reg.start_validation(s.skill_id)
    reg.mark_verified(s.skill_id)
    reg.activate(s.skill_id)
    r = orch.run("research user prefs", simple=False, content="report\n")
    assert r.status == STATUS_COMPLETED
    research = next(t for t in r.tasks if t.agent_name == "researcher")
    evidence = research.outputs.get("evidence", {})
    assert "skills_found" in evidence or "memories_found" in evidence


def test_j_experience_recording(orch: Orchestrator, stores) -> None:
    reg, exp, mem, pipe = stores
    r = orch.run("record exp", simple=True, content="data\n", record_experience=True)
    assert r.status == STATUS_COMPLETED
    assert r.experience_id
    loaded = exp.get(r.experience_id)
    assert loaded is not None
    assert loaded.outcome == "success"
    # reload
    exp2 = ExperienceStore(stores[0].db_path if hasattr(stores[0], "db_path") else exp.db_path)
    assert exp2.get(r.experience_id) is not None
    exp2.close()


def test_k_approval_boundary(orch: Orchestrator, workspace: Path) -> None:
    r = orch.run(
        "protected action",
        simple=True,
        requires_approval=True,
        content="should not write yet\n",
        record_experience=False,
    )
    assert r.status == STATUS_REQUIRES_APPROVAL
    # coder blocked — file may not exist
    coder = next(t for t in r.tasks if t.agent_name == "coder")
    assert coder.status == STATUS_REQUIRES_APPROVAL


def test_l_regression_imports() -> None:
    from jarvis.config import load_config
    from jarvis.memory import MemoryStore
    from jarvis.skills import SkillRegistry
    from jarvis.ai.client import GeminiClient

    assert load_config()["assistant_name"] == "Jarvis"
    c = GeminiClient(api_key=None)
    assert c.available is False
