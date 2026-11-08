"""SQLite knowledge store. Does not touch memory/resources/skills databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    content TEXT NOT NULL,
    source_url TEXT NOT NULL,
    verified INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_url TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class ResearchStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def add_knowledge(self, title: str, content: str, source_url: str, *, category: str = "", tags: str = "", verified: bool = False, created_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO knowledge (title, category, tags, content, source_url, verified, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (title, category, tags, content, source_url, int(verified), created_at, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def find_duplicate(self, title: str, source_url: str) -> Optional[int]:
        row = self.conn.execute(
            "SELECT id FROM knowledge WHERE lower(title)=lower(?) AND source_url=? LIMIT 1",
            (title, source_url),
        ).fetchone()
        return int(row["id"]) if row else None

    def search(self, query: str, *, category: str = "", limit: int = 20) -> list[dict]:
        like = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM knowledge WHERE (title LIKE ? OR content LIKE ?) AND (?='' OR category=?) ORDER BY id DESC LIMIT ?",
            (like, like, category, category, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_note(self, project: str, title: str, body: str, source_url: str, created_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO notes (project, title, body, source_url, created_at) VALUES (?,?,?,?,?)",
            (project, title, body, source_url, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_history(self, action: str, detail: str, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO history (action, detail, created_at) VALUES (?,?,?)",
            (action, detail[:200], created_at),
        )
        self.conn.commit()
