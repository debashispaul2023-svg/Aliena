"""Persistent experience store for task execution traces."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from .models import Experience

try:
    from jarvis.memory.store import looks_like_secret
except Exception:  # pragma: no cover
    def looks_like_secret(text: str) -> bool:  # type: ignore
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json_loads(text: str, default: Any = None) -> Any:
    if default is None:
        default = []
    try:
        return json.loads(text or "null") or default
    except Exception:
        return default


def _redact_str(text: str) -> str:
    if not text:
        return text
    import re

    text = re.sub(
        r"(?i)(api[_\s-]?key|password|passwd|secret|token|bearer)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9]{20,}\b", "[REDACTED]", text)
    text = re.sub(r"\bAIza[0-9A-Za-z\-_]{20,}\b", "[REDACTED]", text)
    text = re.sub(r"\b(ghp|gho)_[A-Za-z0-9]{20,}\b", "[REDACTED]", text)
    return text


def _redact_list(items: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for item in items:
        if isinstance(item, str):
            if looks_like_secret(item):
                out.append("[REDACTED]")
            else:
                out.append(_redact_str(item))
        elif isinstance(item, dict):
            out.append(
                {
                    k: ("[REDACTED]" if looks_like_secret(str(v)) else _redact_str(str(v)) if isinstance(v, str) else v)
                    for k, v in item.items()
                }
            )
        else:
            out.append(item)
    return out


VALID_OUTCOMES = {"success", "failure", "partial", "unknown"}


class ExperienceStore:
    """SQLite store for completed/failed task experiences.

    Does not invent outcomes — caller must supply a truthful outcome value.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._lock = threading.RLock()  # serialises public methods (see install_locking)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiences (
                experience_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                objective TEXT NOT NULL,
                task_plan TEXT NOT NULL DEFAULT '[]',
                tools_used TEXT NOT NULL DEFAULT '[]',
                agents_used TEXT NOT NULL DEFAULT '[]',
                skills_used TEXT NOT NULL DEFAULT '[]',
                errors TEXT NOT NULL DEFAULT '[]',
                fixes TEXT NOT NULL DEFAULT '[]',
                resources TEXT NOT NULL DEFAULT '[]',
                test_results TEXT NOT NULL DEFAULT '[]',
                outcome TEXT NOT NULL DEFAULT 'unknown',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp_task ON experiences(task_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp_outcome ON experiences(outcome)"
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def get_by_task_id(self, task_id: str) -> Optional[Experience]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM experiences WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        )
        row = cur.fetchone()
        return self._row_to_exp(row) if row else None

    def record(
        self,
        task_id: str,
        objective: str,
        task_plan: Optional[Sequence[str]] = None,
        tools_used: Optional[Sequence[str]] = None,
        agents_used: Optional[Sequence[str]] = None,
        skills_used: Optional[Sequence[str]] = None,
        errors: Optional[Sequence[str]] = None,
        fixes: Optional[Sequence[str]] = None,
        resources: Optional[Sequence[str]] = None,
        test_results: Optional[Sequence[dict[str, Any]]] = None,
        outcome: str = "unknown",
        notes: str = "",
        completed: bool = True,
        idempotent: bool = False,
    ) -> Experience:
        """Persist an experience. With idempotent=True, reuses existing row for task_id."""
        outcome = (outcome or "unknown").lower()
        if outcome not in VALID_OUTCOMES:
            outcome = "unknown"

        tid = task_id or str(uuid.uuid4())
        if idempotent:
            existing = self.get_by_task_id(tid)
            if existing is not None:
                return existing

        # Redact secrets from free-text fields before storage
        objective_clean = _redact_str((objective or "").strip() or "unspecified")
        notes_clean = _redact_str(notes or "")
        plan_clean = _redact_list(list(task_plan or []))
        errors_clean = _redact_list(list(errors or []))
        fixes_clean = _redact_list(list(fixes or []))
        resources_clean = _redact_list(list(resources or []))
        tests_clean = _redact_list(list(test_results or []))

        now = _utc_now()
        exp = Experience(
            experience_id=str(uuid.uuid4()),
            task_id=tid,
            objective=objective_clean,
            task_plan=plan_clean,  # type: ignore[arg-type]
            tools_used=list(tools_used or []),
            agents_used=list(agents_used or []),
            skills_used=list(skills_used or []),
            errors=errors_clean,  # type: ignore[arg-type]
            fixes=fixes_clean,  # type: ignore[arg-type]
            resources=resources_clean,  # type: ignore[arg-type]
            test_results=tests_clean,  # type: ignore[arg-type]
            outcome=outcome,
            notes=notes_clean,
            created_at=now,
            completed_at=now if completed else None,
        )
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO experiences (
                experience_id, task_id, objective, task_plan, tools_used,
                agents_used, skills_used, errors, fixes, resources,
                test_results, outcome, notes, created_at, completed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                exp.experience_id,
                exp.task_id,
                exp.objective,
                _json_dumps(exp.task_plan),
                _json_dumps(exp.tools_used),
                _json_dumps(exp.agents_used),
                _json_dumps(exp.skills_used),
                _json_dumps(exp.errors),
                _json_dumps(exp.fixes),
                _json_dumps(exp.resources),
                _json_dumps(exp.test_results),
                exp.outcome,
                exp.notes,
                exp.created_at,
                exp.completed_at,
            ),
        )
        self._conn.commit()
        return exp

    def get(self, experience_id: str) -> Optional[Experience]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM experiences WHERE experience_id = ?", (experience_id,)
        )
        row = cur.fetchone()
        return self._row_to_exp(row) if row else None

    def list_by_outcome(self, outcome: str, limit: int = 50) -> list[Experience]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT * FROM experiences WHERE outcome = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (outcome, limit),
        )
        return [self._row_to_exp(r) for r in cur.fetchall()]

    def list_recent(self, limit: int = 20) -> list[Experience]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM experiences ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._row_to_exp(r) for r in cur.fetchall()]

    def search(self, query: str, limit: int = 20) -> list[Experience]:
        q = f"%{(query or '').strip().lower()}%"
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT * FROM experiences
            WHERE lower(objective) LIKE ? OR lower(notes) LIKE ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (q, q, limit),
        )
        return [self._row_to_exp(r) for r in cur.fetchall()]

    def count(self, outcome: Optional[str] = None) -> int:
        cur = self._conn.cursor()
        if outcome:
            cur.execute(
                "SELECT COUNT(*) FROM experiences WHERE outcome = ?", (outcome,)
            )
        else:
            cur.execute("SELECT COUNT(*) FROM experiences")
        return int(cur.fetchone()[0])

    def _row_to_exp(self, row: sqlite3.Row) -> Experience:
        return Experience(
            experience_id=row["experience_id"],
            task_id=row["task_id"],
            objective=row["objective"],
            task_plan=_json_loads(row["task_plan"], []),
            tools_used=_json_loads(row["tools_used"], []),
            agents_used=_json_loads(row["agents_used"], []),
            skills_used=_json_loads(row["skills_used"], []),
            errors=_json_loads(row["errors"], []),
            fixes=_json_loads(row["fixes"], []),
            resources=_json_loads(row["resources"], []),
            test_results=_json_loads(row["test_results"], []),
            outcome=row["outcome"],
            notes=row["notes"] or "",
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )


from jarvis.memory.store import install_locking as _install_locking  # noqa: E402

_install_locking(ExperienceStore)
