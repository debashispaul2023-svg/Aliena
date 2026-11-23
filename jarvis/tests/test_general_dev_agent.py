"""General-purpose development agent tests. No generated-code execution."""

from pathlib import Path

import pytest

from jarvis.dev.restaurant_builder import RestaurantBuilder
from jarvis.dev.task_understanding import TaskUnderstanding
from jarvis.dev.workspace_writer import WorkspaceWriter


def test_parse_restaurant_request():
    spec = TaskUnderstanding().parse("Create a complete restaurant website with frontend, backend, database, menu, contact and admin")
    assert spec.needs_frontend
    assert spec.needs_backend
    assert "menu" in spec.features


def test_path_traversal_rejected(tmp_path: Path):
    writer = WorkspaceWriter(tmp_path)
    with pytest.raises(ValueError):
        writer.write("../secret.txt", "no")


def test_restaurant_files_created(tmp_path: Path):
    result = RestaurantBuilder().build("Create a restaurant website", tmp_path / "site")
    assert (tmp_path / "site" / "frontend" / "index.html").exists()
    assert (tmp_path / "site" / "backend" / "app.py").exists()
    assert (tmp_path / "site" / "database" / "schema.sql").exists()
    assert result["executed"] is False
    assert result["phase6f"] == "BLOCKED"
