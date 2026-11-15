"""SQLite productivity store. Does not touch memory/resources/skills databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'MEDIUM',
    category TEXT DEFAULT '',
    project_id INTEGER,
    due_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    deadline TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    remind_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    depends_on INTEGER NOT NULL,
    UNIQUE(task_id, depends_on)
);
"""


class ProductivityStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def add_project(self, name: str, deadline: str | None, created_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO projects (name, deadline, created_at) VALUES (?,?,?)",
            (name, deadline, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_task(self, title: str, description: str, priority: str, category: str, project_id: Optional[int], due_at: str | None, created_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO tasks (title, description, priority, category, project_id, due_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (title, description, priority, category, project_id, due_at, created_at, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_task(self, task_id: int, **fields: str) -> None:
        allowed = {"title", "description", "status", "priority", "category", "due_at", "updated_at"}
        sets = []
        values = []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"invalid field: {key}")
            sets.append(f"{key}=?")
            values.append(value)
        if not sets:
            return
        if "updated_at" not in fields:
            sets.append("updated_at=?")
            values.append(fields.get("status", ""))
        values.append(task_id)
        self.conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", values)
        self.conn.commit()

    def list_tasks(self, *, status: str = "", project_id: Optional[int] = None) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE (?='' OR status=?) AND (? IS NULL OR project_id=?) ORDER BY CASE priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, due_at",
            (status, status, project_id, project_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_reminder(self, task_id: int, remind_at: str, created_at: str) -> int:
        existing = self.conn.execute(
            "SELECT id FROM reminders WHERE task_id=? AND remind_at=? AND status='pending'",
            (task_id, remind_at),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = self.conn.execute(
            "INSERT INTO reminders (task_id, remind_at, created_at) VALUES (?,?,?)",
            (task_id, remind_at, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_dependency(self, task_id: int, depends_on: int) -> None:
        if task_id == depends_on:
            raise ValueError("circular dependency")
        self.conn.execute(
            "INSERT OR IGNORE INTO dependencies (task_id, depends_on) VALUES (?,?)",
            (task_id, depends_on),
        )
        self.conn.commit()
        if self._has_cycle():
            self.conn.execute("DELETE FROM dependencies WHERE task_id=? AND depends_on=?", (task_id, depends_on))
            self.conn.commit()
            raise ValueError("circular dependency")

    def _has_cycle(self) -> bool:
        rows = self.conn.execute("SELECT task_id, depends_on FROM dependencies").fetchall()
        graph: dict[int, list[int]] = {}
        for row in rows:
            graph.setdefault(int(row["task_id"]), []).append(int(row["depends_on"]))
        seen, stack = set(), set()

        def visit(node: int) -> bool:
            if node in stack:
                return True
            if node in seen:
                return False
            seen.add(node)
            stack.add(node)
            for nxt in graph.get(node, []):
                if visit(nxt):
                    return True
            stack.remove(node)
            return False

        return any(visit(node) for node in list(graph))

    def history(self, task_id: int, action: str, detail: str, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO history (task_id, action, detail, created_at) VALUES (?,?,?,?)",
            (task_id, action, detail[:200], created_at),
        )
        self.conn.commit()
