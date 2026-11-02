"""Phase 3 end-to-end integration tests.

Uses DeterministicTaskRunner for REAL bounded execution (not synthetic traces).
No network, no GUI, no Gemini. Temporary databases only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.skills import (
    SkillRegistry,
    ExperienceStore,
    LearningPipeline,
    DeterministicTaskRunner,
    STATUS_PROPOSED,
    STATUS_VERIFIED,
    STATUS_ACTIVE,
    STATUS_REJECTED,
)
from jarvis.memory.store import looks_like_secret


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "e2e_skills.db"


@pytest.fixture
def registry(db_path: Path) -> SkillRegistry:
    r = SkillRegistry(db_path)
    yield r
    r.close()


@pytest.fixture
def experiences(db_path: Path) -> ExperienceStore:
    e = ExperienceStore(db_path)
    yield e
    e.close()


@pytest.fixture
def pipeline(registry: SkillRegistry, experiences: ExperienceStore) -> LearningPipeline:
    return LearningPipeline(registry, experiences)


@pytest.fixture
def runner(tmp_path: Path) -> DeterministicTaskRunner:
    return DeterministicTaskRunner(tmp_path / "workspace")


# ------------------------------------------------------------------ Scenario A
def test_scenario_a_successful_task_learns_skill(
    runner: DeterministicTaskRunner, pipeline: LearningPipeline, registry: SkillRegistry
) -> None:
    run = runner.run(
        {
            "kind": "text_transform",
            "task_id": "e2e-success-001",
            "objective": "Uppercase a text file",
            "text": "hello jarvis",
            "mode": "upper",
        }
    )
    assert run.outcome == "success"
    assert any(s.ok for s in run.steps)
    assert (runner.workspace / "output.txt").read_text(encoding="utf-8") == "HELLO JARVIS"

    result = pipeline.run_from_task_result(run, auto_validate=True, idempotent=True)
    assert result["outcome"] == "success"
    assert result["experience_id"]
    assert result["skill_id"]
    assert result["validated"] is True
    assert result["skill_status"] == STATUS_VERIFIED

    skill = registry.get(result["skill_id"])
    assert skill is not None
    assert skill.status == STATUS_VERIFIED  # not auto-ACTIVE
    assert skill.procedure
    assert skill.source_task == "e2e-success-001"


# ------------------------------------------------------------------ Scenario B
def test_scenario_b_failed_task_does_not_propose_success_skill(
    runner: DeterministicTaskRunner, pipeline: LearningPipeline, experiences: ExperienceStore
) -> None:
    run = runner.run(
        {
            "kind": "intentional_fail",
            "task_id": "e2e-fail-001",
            "objective": "Task that fails on purpose",
        }
    )
    assert run.outcome == "failure"
    assert any(not s.ok for s in run.steps)

    result = pipeline.run_from_task_result(run, auto_validate=True)
    assert result["outcome"] == "failure"
    assert result["skill_id"] is None
    assert experiences.count("failure") >= 1


# ------------------------------------------------------------------ Scenario C
def test_scenario_c_invalid_procedure_rejected(registry: SkillRegistry) -> None:
    s = registry.create_skill(name="bad_skill", procedure=[])
    registry.start_validation(s.skill_id)
    ok, failures = registry.run_structural_validation(s.skill_id)
    assert ok is False
    rejected = registry.mark_rejected(s.skill_id, reason="; ".join(failures))
    assert rejected.status == STATUS_REJECTED
    with pytest.raises(ValueError):
        registry.activate(rejected.skill_id)


# ------------------------------------------------------------------ Scenario D
def test_scenario_d_restart_and_recovery(
    runner: DeterministicTaskRunner, tmp_path: Path
) -> None:
    db = tmp_path / "recover.db"
    r1 = SkillRegistry(db)
    e1 = ExperienceStore(db)
    p1 = LearningPipeline(r1, e1)
    run = runner.run(
        {
            "kind": "file_checksum",
            "task_id": "e2e-recover-001",
            "objective": "Checksum a local file",
            "content": "payload-data",
        }
    )
    assert run.outcome == "success"
    result = p1.run_from_task_result(run, auto_validate=True, idempotent=True)
    skill_id = result["skill_id"]
    exp_id = result["experience_id"]
    assert skill_id and exp_id
    r1.close()
    e1.close()

    r2 = SkillRegistry(db)
    e2 = ExperienceStore(db)
    skill = r2.get(skill_id)
    exp = e2.get(exp_id)
    assert skill is not None
    assert skill.status == STATUS_VERIFIED
    assert exp is not None
    assert exp.outcome == "success"
    r2.close()
    e2.close()


# ------------------------------------------------------------------ Scenario E
def test_scenario_e_versioning_and_rollback(registry: SkillRegistry) -> None:
    v1 = registry.create_skill(
        name="e2e_versioned",
        procedure=[{"step": 1, "action": "original"}],
    )
    registry.mark_verified(registry.start_validation(v1.skill_id).skill_id)
    registry.activate(v1.skill_id)
    assert registry.get(v1.skill_id).status == STATUS_ACTIVE

    v2 = registry.create_new_version(v1.skill_id, procedure=[{"step": 1, "action": "updated"}])
    assert v2.version == v1.version + 1
    assert v2.status == STATUS_PROPOSED
    assert registry.get(v1.skill_id).status == STATUS_ACTIVE  # unchanged

    registry.mark_verified(registry.start_validation(v2.skill_id).skill_id)
    registry.activate(v2.skill_id)
    assert registry.get(v2.skill_id).status == STATUS_ACTIVE
    assert registry.get(v1.skill_id).status == STATUS_VERIFIED

    rolled = registry.rollback_to_version("e2e_versioned", version=v1.version)
    assert rolled.skill_id == v1.skill_id
    assert rolled.status == STATUS_ACTIVE
    assert registry.get(v2.skill_id).status == STATUS_VERIFIED


# ------------------------------------------------------------------ Scenario F
def test_scenario_f_duplicate_execution_idempotent(
    runner: DeterministicTaskRunner, pipeline: LearningPipeline, experiences: ExperienceStore, registry: SkillRegistry
) -> None:
    task = {
        "kind": "text_transform",
        "task_id": "e2e-dup-001",
        "objective": "Dedup transform",
        "text": "abc",
        "mode": "lower",
    }
    run1 = runner.run(task)
    r1 = pipeline.run_from_task_result(run1, auto_validate=True, idempotent=True)
    run2 = runner.run(task)  # same task_id
    r2 = pipeline.run_from_task_result(run2, auto_validate=True, idempotent=True)

    # Same experience row reused
    assert r1["experience_id"] == r2["experience_id"]
    # Skill not duplicated for same source_task + name
    assert r1["skill_id"] == r2["skill_id"]
    matches = [s for s in registry.list_by_name(registry.get(r1["skill_id"]).name) if s.source_task == "e2e-dup-001"]
    assert len(matches) == 1


# ------------------------------------------------------------------ Scenario G
def test_scenario_g_secrets_not_persisted(
    runner: DeterministicTaskRunner, pipeline: LearningPipeline, experiences: ExperienceStore
) -> None:
    # Runner refuses secret payload
    run = runner.run(
        {
            "kind": "text_transform",
            "task_id": "e2e-secret-001",
            "objective": "Should refuse secret",
            "text": "api_key=sk-abcdefghijklmnopqrstuvwxyz123456",
            "mode": "upper",
        }
    )
    assert run.outcome == "failure"
    assert any("secret" in e.lower() for e in run.errors)

    # Experience store redacts if somehow passed through
    exp = experiences.record(
        task_id="e2e-secret-002",
        objective="note with password: hunter2_not_real",
        errors=["token=ghp_abcdefghijklmnopqrstuvwxyz"],
        outcome="failure",
        notes="API_KEY=AIzaSyDummyKeyValue123456789012",
    )
    blob = exp.objective + exp.notes + " ".join(exp.errors)
    assert "ghp_" not in blob
    assert "AIza" not in blob or "REDACTED" in blob
    assert not looks_like_secret(exp.notes) or "REDACTED" in exp.notes


# ------------------------------------------------------------------ Scenario H
def test_scenario_h_regression_imports() -> None:
    """Existing modules remain importable and basic APIs work."""
    from jarvis.config import load_config, DEFAULT_CONFIG
    from jarvis.logger import setup_logging
    from jarvis.ai.client import GeminiClient
    from jarvis.memory import MemoryStore

    assert DEFAULT_CONFIG["assistant_name"] == "Jarvis"
    cfg = load_config()
    assert "speech_languages" in cfg
    client = GeminiClient(api_key=None)
    assert client.available is False
    # MemoryStore still constructs
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "m.db"
    ms = MemoryStore(p)
    rec = ms.save("regression fact", category="long_term")
    assert rec is not None
    ms.close()


def test_invalid_lifecycle_transition_errors(registry: SkillRegistry) -> None:
    s = registry.create_skill(
        name="transition_guard",
        procedure=[{"step": 1, "action": "x"}],
    )
    with pytest.raises(ValueError):
        registry.transition(s.skill_id, STATUS_ACTIVE)
    with pytest.raises(ValueError):
        registry.activate(s.skill_id)


def test_failed_validation_cannot_activate(registry: SkillRegistry) -> None:
    s = registry.create_skill(name="no_steps", procedure=[])
    registry.start_validation(s.skill_id)
    ok, _ = registry.run_structural_validation(s.skill_id)
    assert not ok
    registry.mark_rejected(s.skill_id, reason="empty")
    with pytest.raises(ValueError):
        registry.activate(s.skill_id)
    assert registry.get(s.skill_id).status == STATUS_REJECTED
