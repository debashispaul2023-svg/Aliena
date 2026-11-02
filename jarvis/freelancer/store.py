"""Persistent freelancer store. Separate from protected Jarvis databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    budget TEXT,
    url TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    score REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_ext ON jobs(platform, external_id);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    body TEXT NOT NULL,
    bid_amount TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    target_id TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS earnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    kind TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class FreelancerStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def audit(self, event: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO audit(event, detail) VALUES (?, ?)", (event, detail)
        )
        self.conn.commit()

    def add_job(self, **fields: Any) -> int:
        cur = self.conn.execute(
            """INSERT INTO jobs(platform, external_id, title, description, budget, url, status, score)
               VALUES (:platform, :external_id, :title, :description, :budget, :url, :status, :score)""",
            {
                "platform": fields.get("platform", "manual"),
                "external_id": fields.get("external_id"),
                "title": fields["title"],
                "description": fields.get("description", ""),
                "budget": fields.get("budget"),
                "url": fields.get("url"),
                "status": fields.get("status", "discovered"),
                "score": fields.get("score"),
            },
        )
        self.conn.commit()
        self.audit("job_added", str(cur.lastrowid))
        return int(cur.lastrowid)

    def list_jobs(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def add_proposal(self, job_id: int, body: str, bid_amount: Optional[str] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO proposals(job_id, body, bid_amount) VALUES (?, ?, ?)",
            (job_id, body, bid_amount),
        )
        self.conn.commit()
        self.audit("proposal_drafted", str(cur.lastrowid))
        return int(cur.lastrowid)

    def record_approval(self, action: str, target_id: str, approved: bool) -> int:
        cur = self.conn.execute(
            "INSERT INTO approvals(action, target_id, approved) VALUES (?, ?, ?)",
            (action, target_id, 1 if approved else 0),
        )
        self.conn.commit()
        self.audit("approval", f"{action}:{target_id}:{approved}")
        return int(cur.lastrowid)

    def is_approved(self, action: str, target_id: str) -> bool:
        row = self.conn.execute(
            "SELECT approved FROM approvals WHERE action=? AND target_id=? ORDER BY id DESC LIMIT 1",
            (action, target_id),
        ).fetchone()
        return bool(row and row["approved"])

    def add_earning(self, project: str, amount: float, kind: str, currency: str = "USD", note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO earnings(project, amount, currency, kind, note) VALUES (?, ?, ?, ?, ?)",
            (project, amount, currency, kind, note),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def income_total(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM earnings WHERE kind='income'"
        ).fetchone()
        return float(row["s"])

    def close(self) -> None:
        self.conn.close()
