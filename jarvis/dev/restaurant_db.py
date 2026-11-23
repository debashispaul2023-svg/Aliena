"""SQLite-backed restaurant data layer. Used by the generated project and tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS menu (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  price INTEGER NOT NULL CHECK(price >= 0)
);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  message TEXT NOT NULL
);
"""


class RestaurantDB:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript(SCHEMA)

    def add_menu(self, name: str, price: int) -> int:
        if not name.strip() or price < 0:
            raise ValueError("invalid menu item")
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT INTO menu(name, price) VALUES (?, ?)", (name.strip(), price))
            return int(cur.lastrowid)

    def list_menu(self) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT id, name, price FROM menu ORDER BY id").fetchall()
        return [{"id": r[0], "name": r[1], "price": r[2]} for r in rows]

    def add_contact(self, name: str, message: str) -> int:
        if not name.strip() or not message.strip():
            raise ValueError("invalid contact")
        with sqlite3.connect(self.path) as db:
            cur = db.execute("INSERT INTO contacts(name, message) VALUES (?, ?)", (name.strip(), message.strip()))
            return int(cur.lastrowid)
