"""Deep development engine tests. Generated code is not executed on the host."""

from pathlib import Path

import pytest

from jarvis.dev.orchestrator import DevOrchestrator
from jarvis.dev.project_memory import ProjectMemory
from jarvis.dev.restaurant_db import RestaurantDB


def test_orchestrator_sequential():
    tasks = DevOrchestrator().run("build restaurant website")
    assert [t.status for t in tasks] == ["done"] * 6


def test_restaurant_db_roundtrip(tmp_path: Path):
    db = RestaurantDB(tmp_path / "rest.db")
    db.add_menu("Rice", 120)
    assert db.list_menu()[0]["name"] == "Rice"
    with pytest.raises(ValueError):
        db.add_contact("", "hi")
    assert db.add_contact("Ada", "hello") > 0


def test_project_memory_separate(tmp_path: Path):
    mem = ProjectMemory(tmp_path / "project-memory.json")
    mem.add({"event": "planned"})
    assert mem.all()[0]["event"] == "planned"
