"""Restaurant website generator. Writes files only. Does not run generated code."""

from __future__ import annotations

from pathlib import Path

from jarvis.dev.architect import ProjectArchitect
from jarvis.dev.task_understanding import TaskUnderstanding
from jarvis.dev.workspace_writer import WorkspaceWriter


class RestaurantBuilder:
    def build(self, request: str, root: Path) -> dict:
        spec = TaskUnderstanding().parse(request)
        plan = ProjectArchitect().plan(spec)
        writer = WorkspaceWriter(root)
        writer.write(
            "frontend/index.html",
            "<!doctype html><html><head><meta charset='utf-8'><title>Restaurant</title></head>"
            "<body><h1>Restaurant</h1><section id='menu'></section><form id='contact'></form></body></html>",
        )
        writer.write(
            "backend/app.py",
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        body = b'{\"menu\":[]}'\n"
            "        self.send_response(200)\n"
            "        self.end_headers()\n"
            "        self.wfile.write(body)\n"
            "if __name__ == '__main__':\n"
            "    HTTPServer(('127.0.0.1', 8000), Handler).serve_forever()\n",
        )
        writer.write(
            "database/schema.sql",
            "CREATE TABLE IF NOT EXISTS menu (id INTEGER PRIMARY KEY, name TEXT, price INTEGER);\n"
            "CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, message TEXT);\n",
        )
        writer.write(
            "tests/test_files.py",
            "from pathlib import Path\n"
            "def test_files_exist():\n"
            "    root = Path(__file__).resolve().parents[1]\n"
            "    assert (root / 'frontend' / 'index.html').exists()\n",
        )
        writer.write("README.md", "# Restaurant\n\nStatic frontend, stdlib backend, SQLite schema.\n")
        return {"spec": spec, "plan": plan, "executed": False, "phase6f": "BLOCKED"}
