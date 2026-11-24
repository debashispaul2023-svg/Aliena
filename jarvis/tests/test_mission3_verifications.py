"""Mission 3 verifications. Isolation remains unverified."""

from pathlib import Path

import pytest

from jarvis.dev.execution_gate import ExecutionGate, IsolationNotVerified
from jarvis.dev.orchestrator import DevOrchestrator
from jarvis.dev.project_memory import ProjectMemory
from jarvis.dev.restaurant_api import RestaurantAPI
from jarvis.dev.restaurant_db import RestaurantDB


def test_verification_1_execution_gate_blocks():
    gate = ExecutionGate(isolated=False)
    with pytest.raises(IsolationNotVerified):
        gate.run(["python", "backend/app.py"])


def test_verification_2_api_uses_sqlite(tmp_path: Path):
    db = RestaurantDB(tmp_path / "rest.db")
    db.add_menu("Dal", 80)
    api = RestaurantAPI(db)
    status, body = api.get_menu()
    assert status == 200
    assert body["menu"][0]["name"] == "Dal"
    bad, _ = api.post_contact("", "x")
    assert bad == 400
    good, payload = api.post_contact("Ada", "table for 2")
    assert good == 201
    reopened = RestaurantAPI(RestaurantDB(tmp_path / "rest.db"))
    assert reopened.get_menu()[1]["menu"][0]["name"] == "Dal"


def test_verification_3_orchestrator_dependency_and_memory(tmp_path: Path):
    tasks = DevOrchestrator().run("build restaurant", fail="backend")
    by_name = {t.name: t for t in tasks}
    assert by_name["backend"].status == "failed"
    assert by_name["tests"].status == "blocked"
    mem = ProjectMemory(tmp_path / "project-memory.json")
    mem.add({"task": "backend", "status": "failed"})
    reloaded = ProjectMemory(tmp_path / "project-memory.json")
    assert reloaded.all()[0]["status"] == "failed"
