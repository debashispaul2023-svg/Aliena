"""Unit tests for Skill Library, Experience store, and Learning pipeline.

These tests use synthetic traces only. They do not exercise real multi-agent
execution (orchestrator is not implemented yet).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.skills import (
    SkillRegistry,
    ExperienceStore,
    LearningPipeline,
    make_synthetic_trace,
    STATUS_PROPOSED,
    STATUS_VALIDATING,
    STATUS_VERIFIED,
    STATUS_ACTIVE,
    STATUS_REJECTED,
)


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    r = SkillRegistry(tmp_path / "skills.db")
    yield r
    r.close()


@pytest.fixture
def experiences(tmp_path: Path) -> ExperienceStore:
    e = ExperienceStore(tmp_path / "skills.db")
    yield e
    e.close()


@pytest.fixture
def pipeline(registry: SkillRegistry, experiences: ExperienceStore) -> LearningPipeline:
    return LearningPipeline(registry, experiences)


# ------------------------------------------------------------------ Skill CRUD / search
def test_skill_creation_and_retrieval(registry: SkillRegistry) -> None:
    skill = registry.create_skill(
        name="open_app",
        description="Open a desktop application",
        category="pc",
        when_to_use="User asks to open an app",
        procedure=[{"step": 1, "action": "Launch app by name", "tool": "apps"}],
        tags=["desktop"],
    )
    assert skill.skill_id
    assert skill.status == STATUS_PROPOSED
    assert skill.version == 1
    loaded = registry.get(skill.skill_id)
    assert loaded is not None
    assert loaded.name == "open_app"
    assert loaded.procedure[0]["tool"] == "apps"


def test_search_and_filtering(registry: SkillRegistry) -> None:
    registry.create_skill(
        name="pdf_extract",
        description="Extract tables from PDF",
        category="document",
        when_to_use="PDF table extraction",
        procedure=[{"step": 1, "action": "read pdf"}],
        tags=["pdf", "tables"],
    )
    registry.create_skill(
        name="weather_lookup",
        description="Get weather",
        category="web",
        procedure=[{"step": 1, "action": "call weather api"}],
        tags=["weather"],
    )
    hits = registry.search(query="pdf", limit=10)
    assert any(s.name == "pdf_extract" for s in hits)
    docs = registry.search(category="document")
    assert len(docs) == 1


def test_lifecycle_transitions(registry: SkillRegistry) -> None:
    s = registry.create_skill(
        name="lifecycle_demo",
        procedure=[{"step": 1, "action": "do thing"}],
    )
    assert s.status == STATUS_PROPOSED
    s = registry.start_validation(s.skill_id)
    assert s.status == STATUS_VALIDATING
    s = registry.mark_verified(s.skill_id)
    assert s.status == STATUS_VERIFIED
    s = registry.activate(s.skill_id)
    assert s.status == STATUS_ACTIVE
    s = registry.deactivate(s.skill_id)
    assert s.status == STATUS_VERIFIED


def test_failed_validation_rejects(registry: SkillRegistry) -> None:
    s = registry.create_skill(name="empty_proc", procedure=[])  # invalid structure
    registry.start_validation(s.skill_id)
    ok, failures = registry.run_structural_validation(s.skill_id)
    assert ok is False
    assert failures
    rejected = registry.mark_rejected(s.skill_id, reason="; ".join(failures))
    assert rejected.status == STATUS_REJECTED


def test_cannot_activate_unverified(registry: SkillRegistry) -> None:
    s = registry.create_skill(
        name="not_ready",
        procedure=[{"step": 1, "action": "x"}],
    )
    with pytest.raises(ValueError):
        registry.activate(s.skill_id)
    # Still proposed
    assert registry.get(s.skill_id).status == STATUS_PROPOSED


def test_version_update_does_not_replace_active(registry: SkillRegistry) -> None:
    v1 = registry.create_skill(
        name="versioned",
        procedure=[{"step": 1, "action": "old"}],
    )
    registry.start_validation(v1.skill_id)
    registry.mark_verified(v1.skill_id)
    registry.activate(v1.skill_id)
    assert registry.get(v1.skill_id).status == STATUS_ACTIVE

    v2 = registry.create_new_version(v1.skill_id, procedure=[{"step": 1, "action": "new"}])
    assert v2.version == 2
    assert v2.status == STATUS_PROPOSED
    # v1 still active
    assert registry.get(v1.skill_id).status == STATUS_ACTIVE
    # Activating v2 after verify swaps
    registry.start_validation(v2.skill_id)
    registry.mark_verified(v2.skill_id)
    registry.activate(v2.skill_id)
    assert registry.get(v2.skill_id).status == STATUS_ACTIVE
    assert registry.get(v1.skill_id).status == STATUS_VERIFIED


def test_rollback_to_previous_verified(registry: SkillRegistry) -> None:
    v1 = registry.create_skill(
        name="rollback_demo",
        procedure=[{"step": 1, "action": "a"}],
    )
    registry.mark_verified(registry.start_validation(v1.skill_id).skill_id)
    registry.activate(v1.skill_id)

    v2 = registry.create_new_version(v1.skill_id, procedure=[{"step": 1, "action": "b"}])
    registry.mark_verified(registry.start_validation(v2.skill_id).skill_id)
    registry.activate(v2.skill_id)
    assert registry.get(v2.skill_id).status == STATUS_ACTIVE

    rolled = registry.rollback_to_version("rollback_demo", version=1)
    assert rolled.skill_id == v1.skill_id
    assert rolled.status == STATUS_ACTIVE
    assert registry.get(v2.skill_id).status == STATUS_VERIFIED


def test_usage_tracking(registry: SkillRegistry) -> None:
    s = registry.create_skill(
        name="used_skill",
        procedure=[{"step": 1, "action": "x"}],
    )
    registry.record_usage(s.skill_id)
    registry.record_usage(s.skill_id)
    loaded = registry.get(s.skill_id)
    assert loaded is not None
    assert loaded.usage_count == 2


# ------------------------------------------------------------------ Experience
def test_experience_persistence(experiences: ExperienceStore, tmp_path: Path) -> None:
    exp = experiences.record(
        task_id="t1",
        objective="Build a hello script",
        tools_used=["code"],
        outcome="success",
        test_results=[{"name": "runs", "passed": True}],
    )
    assert exp.experience_id
    assert experiences.count("success") == 1
    loaded = experiences.get(exp.experience_id)
    assert loaded is not None
    assert loaded.objective == "Build a hello script"

    # reopen
    experiences.close()
    e2 = ExperienceStore(tmp_path / "skills.db")
    assert e2.get(exp.experience_id) is not None
    e2.close()


# ------------------------------------------------------------------ Learning pipeline
def test_candidate_from_synthetic_trace(pipeline: LearningPipeline) -> None:
    trace = make_synthetic_trace(success=True)
    result = pipeline.run_pipeline(trace, auto_validate=True)
    assert result["experience_id"]
    assert result["outcome"] == "success"
    assert result["skill_id"]
    assert result["validated"] is True
    assert result["skill_status"] == STATUS_VERIFIED
    # Not auto-activated
    skill = pipeline.registry.get(result["skill_id"])
    assert skill is not None
    assert skill.status == STATUS_VERIFIED
    assert skill.procedure
    # Procedures are structured data, not executable code blobs
    assert isinstance(skill.procedure[0], dict)


def test_failed_trace_does_not_propose_by_default(pipeline: LearningPipeline) -> None:
    trace = make_synthetic_trace(success=False)
    result = pipeline.run_pipeline(trace, auto_validate=True)
    assert result["outcome"] == "failure"
    assert result["skill_id"] is None


def test_skills_persist_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist_skills.db"
    r1 = SkillRegistry(db)
    s = r1.create_skill(
        name="persist_me",
        procedure=[{"step": 1, "action": "stay"}],
    )
    r1.start_validation(s.skill_id)
    r1.mark_verified(s.skill_id)
    r1.activate(s.skill_id)
    sid = s.skill_id
    r1.close()

    r2 = SkillRegistry(db)
    loaded = r2.get(sid)
    assert loaded is not None
    assert loaded.status == STATUS_ACTIVE
    assert loaded.name == "persist_me"
    r2.close()


def test_find_relevant_active(registry: SkillRegistry) -> None:
    s = registry.create_skill(
        name="pdf_table_extraction",
        when_to_use="extract tables from PDF documents",
        procedure=[{"step": 1, "action": "extract"}],
        tags=["pdf"],
    )
    registry.mark_verified(registry.start_validation(s.skill_id).skill_id)
    registry.activate(s.skill_id)
    hits = registry.find_relevant_active("I need PDF tables", limit=5)
    assert any(h.name == "pdf_table_extraction" for h in hits)
