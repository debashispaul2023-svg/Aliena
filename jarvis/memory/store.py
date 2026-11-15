"""SQLite-backed permanent memory for Jarvis.

Supports short-term conversation context, long-term user facts,
preferences, goals, project memories, task history, agent experiences,
and skill references.

Does not store secrets (API keys, passwords, tokens).
"""

from __future__ import annotations

import functools
import json
import re
import sqlite3
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

# Categories used by the system
CATEGORY_SHORT_TERM = "short_term"
CATEGORY_LONG_TERM = "long_term"
CATEGORY_PREFERENCE = "preference"
CATEGORY_GOAL = "goal"
CATEGORY_PROJECT = "project"
CATEGORY_TASK = "task"
CATEGORY_EXPERIENCE = "experience"
CATEGORY_SKILL_REF = "skill_ref"
CATEGORY_USER_PROFILE = "user_profile"
CATEGORY_CONVERSATION = "conversation"  # migrated chat turns
CATEGORY_ARCHIVE = "archive"

VALID_CATEGORIES = {
    CATEGORY_SHORT_TERM,
    CATEGORY_LONG_TERM,
    CATEGORY_PREFERENCE,
    CATEGORY_GOAL,
    CATEGORY_PROJECT,
    CATEGORY_TASK,
    CATEGORY_EXPERIENCE,
    CATEGORY_SKILL_REF,
    CATEGORY_USER_PROFILE,
    CATEGORY_CONVERSATION,
    CATEGORY_ARCHIVE,
}

# Current memory schema version (stored in meta.schema_version). Changes must be
# additive; see ALIENA_DATABASE_SCHEMA.md.
SCHEMA_VERSION = 1

# Patterns that should never be stored as ordinary memories
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_\s-]?key|secret|password|passwd|token|bearer|private[_\s-]?key)\b"),
    re.compile(r"(?i)\b(sk-[a-zA-Z0-9]{20,})\b"),
    re.compile(r"(?i)\b(AIza[0-9A-Za-z\-_]{20,})\b"),
    re.compile(r"(?i)\b(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,})\b"),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _negates(a: str, b: str) -> bool:
    left, right = a.lower(), b.lower()
    pairs = [("live in", "do not live in"), ("likes", "does not like")]
    for pos, neg in pairs:
        if pos in left and neg in right:
            return True
        if pos in right and neg in left:
            return True
    return False


def looks_like_secret(text: str) -> bool:
    """Return True if content appears to contain credentials or secrets."""
    if not text or not text.strip():
        return False
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            return True
    return False


@dataclass
class MemoryRecord:
    id: str
    category: str
    content: str
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5  # 0.0 – 1.0
    confidence: float = 0.8
    source: str = "user"
    created_at: str = ""
    updated_at: str = ""
    last_used: Optional[str] = None
    project_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryStore:
    """Persistent SQLite memory store."""

    def __init__(self, db_path: str | Path) -> None:
        # Re-entrant lock: every public method is serialised (see _install_locking
        # at the bottom of this module). The single shared connection is opened with
        # check_same_thread=False, so without this lock concurrent threads corrupt
        # each other's cursors/transactions (verified defect, Phase 3).
        self._lock = threading.RLock()
        self.last_restore_error: Optional[str] = None
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        # Remember whether this is a brand-new database BEFORE creating anything.
        existed = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone() is not None
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                importance REAL NOT NULL DEFAULT 0.5,
                confidence REAL NOT NULL DEFAULT 0.8,
                source TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used TEXT,
                project_id TEXT
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id)"
        )
        # Migration marker so we only migrate jarvis_memory.json once
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # Version stamp ONLY for newly created databases. An existing database is
        # never written to merely by opening it (protected baseline DBs stay
        # byte-identical); an unstamped existing DB is reported as version 1 by
        # schema_version() because its table layout is identical.
        if not existed:
            cur.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
        self._conn.commit()

    def schema_version(self) -> int:
        """Stored schema version. An existing, unstamped database (the baseline
        layout) reports ``1``; ``0`` only if unreadable / no memories table."""
        try:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", ("schema_version",)
            ).fetchone()
            if row:
                return int(row[0])
            has = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
            return 1 if has else 0
        except Exception:
            return 0

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ CRUD
    def save(
        self,
        content: str,
        category: str = CATEGORY_LONG_TERM,
        tags: Optional[Sequence[str]] = None,
        importance: float = 0.5,
        confidence: float = 0.8,
        source: str = "user",
        project_id: Optional[str] = None,
        record_id: Optional[str] = None,
        allow_duplicate: bool = False,
    ) -> Optional[MemoryRecord]:
        """Insert a memory. Returns None if content looks like a secret or is empty.

        Duplicate prevention: same category + normalized content is skipped
        unless allow_duplicate=True.
        """
        content = (content or "").strip()
        if not content:
            return None
        if looks_like_secret(content):
            return None
        if source in {"mcp", "web", "untrusted"} and confidence > 0.4:
            confidence = 0.4
        if category not in VALID_CATEGORIES:
            category = CATEGORY_LONG_TERM

        if not allow_duplicate and self._find_duplicate(content, category):
            existing = self._find_duplicate(content, category)
            # Touch last_used
            self.touch(existing.id)
            return existing

        now = _utc_now()
        rid = record_id or str(uuid.uuid4())
        tags_list = list(tags) if tags else []
        rec = MemoryRecord(
            id=rid,
            category=category,
            content=content,
            tags=tags_list,
            importance=float(importance),
            confidence=float(confidence),
            source=source,
            created_at=now,
            updated_at=now,
            last_used=now,
            project_id=project_id,
        )
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO memories
            (id, category, content, tags, importance, confidence, source,
             created_at, updated_at, last_used, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.id,
                rec.category,
                rec.content,
                json.dumps(rec.tags),
                rec.importance,
                rec.confidence,
                rec.source,
                rec.created_at,
                rec.updated_at,
                rec.last_used,
                rec.project_id,
            ),
        )
        self._conn.commit()
        return rec

    def _find_duplicate(self, content: str, category: str) -> Optional[MemoryRecord]:
        norm = content.strip().lower()
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM memories WHERE category = ? AND lower(trim(content)) = ?",
            (category, norm),
        )
        row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def get(self, record_id: str) -> Optional[MemoryRecord]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM memories WHERE id = ?", (record_id,))
        row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def update(
        self,
        record_id: str,
        content: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        importance: Optional[float] = None,
        confidence: Optional[float] = None,
        category: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[MemoryRecord]:
        rec = self.get(record_id)
        if not rec:
            return None
        if content is not None:
            if looks_like_secret(content):
                return None
            rec.content = content.strip()
        if tags is not None:
            rec.tags = list(tags)
        if importance is not None:
            rec.importance = float(importance)
        if confidence is not None:
            rec.confidence = float(confidence)
        if category is not None and category in VALID_CATEGORIES:
            rec.category = category
        if project_id is not None:
            rec.project_id = project_id
        rec.updated_at = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE memories SET content=?, tags=?, importance=?, confidence=?,
            category=?, project_id=?, updated_at=? WHERE id=?
            """,
            (
                rec.content,
                json.dumps(rec.tags),
                rec.importance,
                rec.confidence,
                rec.category,
                rec.project_id,
                rec.updated_at,
                rec.id,
            ),
        )
        self._conn.commit()
        return rec

    def delete(self, record_id: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM memories WHERE id = ?", (record_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def delete_by_content_match(
        self, text: str, category: Optional[str] = None, limit: int = 5
    ) -> list[MemoryRecord]:
        """Soft search: return candidates matching text (for confirmation before delete)."""
        return self.search(text, category=category, limit=limit)

    def touch(self, record_id: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE memories SET last_used = ? WHERE id = ?",
            (_utc_now(), record_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ Query
    def list_by_category(
        self, category: str, limit: int = 50, project_id: Optional[str] = None
    ) -> list[MemoryRecord]:
        cur = self._conn.cursor()
        if project_id:
            cur.execute(
                """
                SELECT * FROM memories WHERE category = ? AND project_id = ?
                ORDER BY importance DESC, updated_at DESC LIMIT ?
                """,
                (category, project_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM memories WHERE category = ?
                ORDER BY importance DESC, updated_at DESC LIMIT ?
                """,
                (category, limit),
            )
        return [self._row_to_record(r) for r in cur.fetchall()]

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Simple keyword search over content and tags."""
        tokens = [t for t in re.split(r"\s+", (query or "").strip().lower()) if t]
        if not tokens:
            if category:
                return self.list_by_category(category, limit=limit, project_id=project_id)
            return []

        cur = self._conn.cursor()
        clauses = ["1=1"]
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)

        # OR match any token in content or tags
        token_clauses = []
        for t in tokens:
            token_clauses.append("(lower(content) LIKE ? OR lower(tags) LIKE ?)")
            params.extend([f"%{t}%", f"%{t}%"])
        clauses.append("(" + " OR ".join(token_clauses) + ")")

        sql = (
            f"SELECT * FROM memories WHERE {' AND '.join(clauses)} "
            f"ORDER BY importance DESC, updated_at DESC LIMIT ?"
        )
        params.append(limit)
        cur.execute(sql, params)
        results = [self._row_to_record(r) for r in cur.fetchall()]
        for r in results:
            self.touch(r.id)
        return results

    def relevant_for_prompt(
        self, query: str, limit: int = 8, max_chars: int = 1200
    ) -> list[MemoryRecord]:
        """Retrieve a small set of relevant long-term memories for LLM context.

        Prefers long_term, preference, goal, user_profile, project.
        """
        preferred = [
            CATEGORY_USER_PROFILE,
            CATEGORY_PREFERENCE,
            CATEGORY_GOAL,
            CATEGORY_LONG_TERM,
            CATEGORY_PROJECT,
        ]
        results: list[MemoryRecord] = []
        seen: set[str] = set()
        # First: keyword search across preferred categories
        for cat in preferred:
            for rec in self.search(query, category=cat, limit=limit):
                if rec.id not in seen:
                    seen.add(rec.id)
                    results.append(rec)
            if len(results) >= limit:
                break
        # Fill with high-importance profile facts if still sparse
        if len(results) < limit:
            for rec in self.list_by_category(CATEGORY_USER_PROFILE, limit=5):
                if rec.id not in seen:
                    seen.add(rec.id)
                    results.append(rec)
            for rec in self.list_by_category(CATEGORY_PREFERENCE, limit=5):
                if rec.id not in seen:
                    seen.add(rec.id)
                    results.append(rec)

        # Cap total character budget
        out: list[MemoryRecord] = []
        total = 0
        for r in results[:limit]:
            if total + len(r.content) > max_chars and out:
                break
            out.append(r)
            total += len(r.content)
        return out

    def archive(self, record_id: str) -> Optional[MemoryRecord]:
        return self.update(record_id, category=CATEGORY_ARCHIVE)

    def backup(self, dest: str | Path) -> Path:
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn.commit()
        with sqlite3.connect(str(path)) as out:
            self._conn.backup(out)
        return path

    def restore(self, src: str | Path) -> int:
        """Replace the live database with a backup. Fail closed.

        Returns the record count after a successful restore. Returns 0 and leaves
        the live database untouched when the source is missing or is not a valid
        memory database; the reason is stored in ``last_restore_error``.

        Before overwriting, the current database is copied to
        ``<db>.pre_restore_<timestamp>`` (never deleted automatically).
        """
        self.last_restore_error = None
        src_path = Path(src)
        if not src_path.exists():
            self.last_restore_error = "source_missing"
            return 0
        try:
            if src_path.resolve() == self.db_path.resolve():
                self.last_restore_error = "source_is_live_db"
                return self.count()
        except Exception:
            pass

        # 1. Validate the source read-only before touching anything.
        uri = src_path.resolve().as_uri() + "?mode=ro"
        try:
            probe = sqlite3.connect(uri, uri=True)
            try:
                check = probe.execute("PRAGMA integrity_check").fetchone()
                has_table = probe.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
                ).fetchone()
            finally:
                probe.close()
        except Exception:
            self.last_restore_error = "source_not_a_valid_database"
            return 0
        if not check or check[0] != "ok":
            self.last_restore_error = "source_failed_integrity_check"
            return 0
        if not has_table:
            self.last_restore_error = "source_has_no_memories_table"
            return 0

        # 2. Safety copy of the current database.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safety = self.db_path.with_name(f"{self.db_path.name}.pre_restore_{stamp}")
        try:
            self.backup(safety)
        except Exception:
            self.last_restore_error = "safety_backup_failed"
            return 0

        # 3. Copy through SQLite's backup API (transactional; no raw byte overwrite).
        try:
            src_conn = sqlite3.connect(uri, uri=True)
            try:
                src_conn.backup(self._conn)
            finally:
                src_conn.close()
            self._init_schema()
        except Exception:
            self.last_restore_error = "restore_failed_live_db_unchanged_or_see_safety_copy"
            try:
                return self.count()
            except Exception:
                return 0
        return self.count()

    def integrity_check(self) -> bool:
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")

    def find_contradictions(self) -> list[tuple[MemoryRecord, MemoryRecord]]:
        rows = self.list_by_category(CATEGORY_LONG_TERM, limit=200)
        hits = []
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if _negates(a.content, b.content):
                    hits.append((a, b))
        return hits

    def count(self, category: Optional[str] = None) -> int:
        cur = self._conn.cursor()
        if category:
            cur.execute("SELECT COUNT(*) FROM memories WHERE category = ?", (category,))
        else:
            cur.execute("SELECT COUNT(*) FROM memories")
        return int(cur.fetchone()[0])

    # ------------------------------------------------------------------ Migration
    def migrate_from_json(
        self, json_path: str | Path, backup_dir: Optional[str | Path] = None
    ) -> int:
        """One-time migration of jarvis_memory.json conversation turns.

        Backs up the source file, skips if already migrated, never deletes original.
        Returns number of records inserted.
        """
        path = Path(json_path)
        if not path.exists():
            return 0

        cur = self._conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key = ?", ("json_memory_migrated",))
        row = cur.fetchone()
        if row and row[0] == "1":
            return 0  # already migrated

        # Backup
        if backup_dir is None:
            backup_dir = path.parent / "jarvis_backup"
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"jarvis_memory.json.migrated_{stamp}"
        try:
            dest.write_bytes(path.read_bytes())
        except Exception:
            pass  # migration still proceeds even if backup fails

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(data, list):
            return 0

        # Idempotent on re-run: a previous run that was interrupted before the
        # marker was written already inserted some rows. Count what exists per
        # (content, timestamp) so only the shortfall is inserted. Identical turns
        # that genuinely repeat in the source are still preserved (counted).
        existing: Counter = Counter()
        existing_by_content: Counter = Counter()  # for source turns that have no timestamp
        for r in cur.execute(
            "SELECT content, created_at FROM memories WHERE source = ? AND category = ?",
            ("migration", CATEGORY_CONVERSATION),
        ).fetchall():
            existing[(r[0], r[1])] += 1
            existing_by_content[r[0]] += 1

        inserted = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            role = item.get("role", "user")
            text = (item.get("text") or "").strip()
            if not text or looks_like_secret(text):
                continue
            ts = item.get("time")
            content = f"{role}: {text}"
            if ts and existing[(content, ts)] > 0:
                existing[(content, ts)] -= 1  # already migrated by an earlier run
                existing_by_content[content] -= 1
                continue
            if not ts and existing_by_content[content] > 0:
                existing_by_content[content] -= 1  # no timestamp to compare: match on content
                continue
            ts = ts or _utc_now()
            rec = self.save(
                content=content,
                category=CATEGORY_CONVERSATION,
                tags=["migrated", role],
                importance=0.3,
                confidence=0.9,
                source="migration",
                allow_duplicate=True,
            )
            if rec:
                # Preserve original timestamp if possible
                cur.execute(
                    "UPDATE memories SET created_at = ?, updated_at = ? WHERE id = ?",
                    (ts, ts, rec.id),
                )
                self._conn.commit()  # keep row + timestamp together if interrupted
                inserted += 1
        self._conn.commit()

        cur.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("json_memory_migrated", "1"),
        )
        self._conn.commit()
        return inserted

    # ------------------------------------------------------------------ Helpers
    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        tags_raw = row["tags"] or "[]"
        try:
            tags = json.loads(tags_raw)
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []
        return MemoryRecord(
            id=row["id"],
            category=row["category"],
            content=row["content"],
            tags=tags,
            importance=row["importance"],
            confidence=row["confidence"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used=row["last_used"],
            project_id=row["project_id"],
        )

    def format_for_prompt(self, records: Iterable[MemoryRecord]) -> str:
        lines = []
        for r in records:
            tag_str = ",".join(r.tags) if r.tags else ""
            prefix = f"[{r.category}"
            if tag_str:
                prefix += f"|{tag_str}"
            prefix += "]"
            lines.append(f"{prefix} {r.content}")
        return "\n".join(lines)


def _install_locking(cls: type) -> None:
    """Serialise every public method of ``cls`` with ``self._lock`` (an RLock).

    ``functools.wraps`` keeps names, docstrings and ``inspect.signature`` intact,
    so the public API is unchanged. The lock is re-entrant, so public methods may
    call each other (e.g. ``archive`` -> ``update`` -> ``get``).
    """
    for name, attr in list(vars(cls).items()):
        if name.startswith("_") or not callable(attr) or isinstance(attr, (staticmethod, classmethod, property)):
            continue

        def _make(fn):
            @functools.wraps(fn)
            def locked(self, *args, **kwargs):
                with self._lock:
                    return fn(self, *args, **kwargs)

            return locked

        setattr(cls, name, _make(attr))


_install_locking(MemoryStore)

# Public alias so sibling Part A modules (skills) reuse the same locking helper.
install_locking = _install_locking
