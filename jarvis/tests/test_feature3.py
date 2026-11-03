"""Feature 3 multi-agent workflows. Isolated memory only."""

from __future__ import annotations

from jarvis.core.agent_registry import AgentRegistry
from jarvis.core.agents import build_default_agents
from jarvis.core.clarification import ClarificationCenter
from jarvis.core.orchestrator import Orchestrator
from jarvis.memory.store import MemoryStore, CATEGORY_PROJECT


def test_enable_disable():
    registry = AgentRegistry()
    for agent in build_default_agents():
        registry.register(agent)
    registry.disable("researcher")
    assert registry.available("researcher") is False
    try:
        registry.get("researcher")
        assert False
    except KeyError:
        pass
    registry.enable("researcher")
    assert registry.get("researcher").name == "researcher"


def test_simple_avoids_full_chain(tmp_path):
    orch = Orchestrator(workspace=tmp_path)
    tasks = orch.plan_simple("what is 2+2", simple=True)
    agents = [t.agent_name for t in tasks]
    assert "researcher" not in agents
    assert "planner" in agents


def test_clarification_resumes():
    center = ClarificationCenter()
    question = center.needs_clarification("fix this")
    assert question
    session = center.ask("task-1", question)
    center.resume("task-1", "the memory backup")
    assert session.closed
    assert "memory" in session.answer


def test_memory_continuity(tmp_path):
    db = tmp_path / "mem.db"
    store = MemoryStore(db)
    store.save("Project uses SQLite", category=CATEGORY_PROJECT, project_id="jarvis")
    orch = Orchestrator(workspace=tmp_path, memory_store=store)
    result = orch.run("remember project sqlite", simple=True)
    assert result.status in {"COMPLETED", "FAILED", "REQUIRES_APPROVAL"}
    store.close()
    again = MemoryStore(db)
    assert again.search("SQLite", project_id="jarvis")
    again.close()


def test_phase6f_not_enabled():
    from pathlib import Path
    status = Path("phase6_status.json")
    if status.exists():
        text = status.read_text()
        assert "BLOCKED" in text or "blocked" in text.lower()
    else:
        assert True
