"""Persistent skill registry with versioning and lifecycle control."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from .models import (
    Skill,
    STATUS_PROPOSED,
    STATUS_VALIDATING,
    STATUS_VERIFIED,
    STATUS_ACTIVE,
    STATUS_REJECTED,
    VALID_STATUSES,
    LIFECYCLE_TRANSITIONS,
)


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


class SkillRegistry:
    """SQLite-backed skill library.

    Only VERIFIED skills may be activated. New versions are stored as separate
    rows linked by parent_skill_id / name lineage; activating a new version
    deactivates the previous ACTIVE skill of the same name.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'general',
                when_to_use TEXT NOT NULL DEFAULT '',
                prerequisites TEXT NOT NULL DEFAULT '[]',
                required_tools TEXT NOT NULL DEFAULT '[]',
                procedure TEXT NOT NULL DEFAULT '[]',
                examples TEXT NOT NULL DEFAULT '[]',
                known_failures TEXT NOT NULL DEFAULT '[]',
                successful_patterns TEXT NOT NULL DEFAULT '[]',
                validation_tests TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL DEFAULT 0.5,
                version INTEGER NOT NULL DEFAULT 1,
                source_task TEXT,
                status TEXT NOT NULL DEFAULT 'PROPOSED',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                usage_count INTEGER NOT NULL DEFAULT 0,
                parent_skill_id TEXT,
                tags TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category)")
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ Create
    def create_skill(
        self,
        name: str,
        description: str = "",
        category: str = "general",
        when_to_use: str = "",
        prerequisites: Optional[Sequence[str]] = None,
        required_tools: Optional[Sequence[str]] = None,
        procedure: Optional[Sequence[dict[str, Any]]] = None,
        examples: Optional[Sequence[str]] = None,
        known_failures: Optional[Sequence[str]] = None,
        successful_patterns: Optional[Sequence[str]] = None,
        validation_tests: Optional[Sequence[dict[str, Any]]] = None,
        confidence: float = 0.5,
        source_task: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        status: str = STATUS_PROPOSED,
        parent_skill_id: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Skill:
        name = (name or "").strip()
        if not name:
            raise ValueError("Skill name is required")
        if status not in VALID_STATUSES:
            status = STATUS_PROPOSED
        # New skills cannot start as ACTIVE
        if status == STATUS_ACTIVE:
            status = STATUS_PROPOSED

        # Version: if parent given, bump; else next version for same name, or 1
        if version is None:
            if parent_skill_id:
                parent = self.get(parent_skill_id)
                version = (parent.version + 1) if parent else 1
            else:
                existing = self.list_by_name(name)
                version = max((s.version for s in existing), default=0) + 1

        now = _utc_now()
        skill = Skill(
            skill_id=str(uuid.uuid4()),
            name=name,
            description=description or "",
            category=category or "general",
            when_to_use=when_to_use or "",
            prerequisites=list(prerequisites or []),
            required_tools=list(required_tools or []),
            procedure=list(procedure or []),
            examples=list(examples or []),
            known_failures=list(known_failures or []),
            successful_patterns=list(successful_patterns or []),
            validation_tests=list(validation_tests or []),
            confidence=float(confidence),
            version=int(version),
            source_task=source_task,
            status=status,
            created_at=now,
            updated_at=now,
            usage_count=0,
            parent_skill_id=parent_skill_id,
            tags=list(tags or []),
        )
        self._insert(skill)
        return skill

    def _insert(self, skill: Skill) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO skills (
                skill_id, name, description, category, when_to_use,
                prerequisites, required_tools, procedure, examples,
                known_failures, successful_patterns, validation_tests,
                confidence, version, source_task, status, created_at,
                updated_at, usage_count, parent_skill_id, tags
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                skill.skill_id,
                skill.name,
                skill.description,
                skill.category,
                skill.when_to_use,
                _json_dumps(skill.prerequisites),
                _json_dumps(skill.required_tools),
                _json_dumps(skill.procedure),
                _json_dumps(skill.examples),
                _json_dumps(skill.known_failures),
                _json_dumps(skill.successful_patterns),
                _json_dumps(skill.validation_tests),
                skill.confidence,
                skill.version,
                skill.source_task,
                skill.status,
                skill.created_at,
                skill.updated_at,
                skill.usage_count,
                skill.parent_skill_id,
                _json_dumps(skill.tags),
            ),
        )
        self._conn.commit()

    def _row_to_skill(self, row: sqlite3.Row) -> Skill:
        return Skill(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            category=row["category"],
            when_to_use=row["when_to_use"],
            prerequisites=_json_loads(row["prerequisites"], []),
            required_tools=_json_loads(row["required_tools"], []),
            procedure=_json_loads(row["procedure"], []),
            examples=_json_loads(row["examples"], []),
            known_failures=_json_loads(row["known_failures"], []),
            successful_patterns=_json_loads(row["successful_patterns"], []),
            validation_tests=_json_loads(row["validation_tests"], []),
            confidence=row["confidence"],
            version=row["version"],
            source_task=row["source_task"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            usage_count=row["usage_count"],
            parent_skill_id=row["parent_skill_id"],
            tags=_json_loads(row["tags"], []),
        )

    # ------------------------------------------------------------------ Read
    def get(self, skill_id: str) -> Optional[Skill]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM skills WHERE skill_id = ?", (skill_id,))
        row = cur.fetchone()
        return self._row_to_skill(row) if row else None

    def list_by_name(self, name: str) -> list[Skill]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM skills WHERE lower(name) = lower(?) ORDER BY version DESC",
            (name,),
        )
        return [self._row_to_skill(r) for r in cur.fetchall()]

    def list_by_status(self, status: str, limit: int = 50) -> list[Skill]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM skills WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        )
        return [self._row_to_skill(r) for r in cur.fetchall()]

    def list_active(self, limit: int = 50) -> list[Skill]:
        return self.list_by_status(STATUS_ACTIVE, limit=limit)

    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        status: Optional[str] = None,
        active_only: bool = False,
        limit: int = 20,
    ) -> list[Skill]:
        clauses = ["1=1"]
        params: list[Any] = []
        if active_only:
            clauses.append("status = ?")
            params.append(STATUS_ACTIVE)
        elif status:
            clauses.append("status = ?")
            params.append(status)
        if category:
            clauses.append("lower(category) = lower(?)")
            params.append(category)
        if query:
            tokens = [t for t in query.strip().lower().split() if len(t) > 1]
            if not tokens:
                tokens = [query.strip().lower()]
            token_clauses = []
            for t in tokens:
                pat = f"%{t}%"
                token_clauses.append(
                    "(lower(name) LIKE ? OR lower(description) LIKE ? OR lower(when_to_use) LIKE ? OR lower(tags) LIKE ?)"
                )
                params.extend([pat, pat, pat, pat])
            if token_clauses:
                # Match if ANY token hits (OR) so natural phrases work
                clauses.append("(" + " OR ".join(token_clauses) + ")")
        if tags:
            for t in tags:
                clauses.append("lower(tags) LIKE ?")
                params.append(f"%{t.lower()}%")

        sql = f"SELECT * FROM skills WHERE {' AND '.join(clauses)} ORDER BY usage_count DESC, confidence DESC LIMIT ?"
        params.append(limit)
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return [self._row_to_skill(r) for r in cur.fetchall()]

    def find_relevant_active(self, query: str, limit: int = 5) -> list[Skill]:
        """Search active skills by name / when_to_use / tags for a user task description."""
        return self.search(query=query, active_only=True, limit=limit)

    def count(self, status: Optional[str] = None) -> int:
        cur = self._conn.cursor()
        if status:
            cur.execute("SELECT COUNT(*) FROM skills WHERE status = ?", (status,))
        else:
            cur.execute("SELECT COUNT(*) FROM skills")
        return int(cur.fetchone()[0])

    # ------------------------------------------------------------------ Lifecycle
    def transition(self, skill_id: str, new_status: str) -> Skill:
        skill = self.get(skill_id)
        if not skill:
            raise KeyError(f"Skill not found: {skill_id}")
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {new_status}")
        allowed = LIFECYCLE_TRANSITIONS.get(skill.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition {skill.status} → {new_status}. Allowed: {sorted(allowed)}"
            )
        if new_status == STATUS_ACTIVE and skill.status != STATUS_VERIFIED:
            # Extra guard: only VERIFIED may become ACTIVE (also enforced by graph)
            raise ValueError("Only VERIFIED skills may be activated")

        # When activating, deactivate other ACTIVE versions of the same name
        if new_status == STATUS_ACTIVE:
            self._deactivate_name(skill.name, except_id=skill.skill_id)

        skill.status = new_status
        skill.updated_at = _utc_now()
        self._update_status_fields(skill)
        return skill

    def _deactivate_name(self, name: str, except_id: Optional[str] = None) -> None:
        cur = self._conn.cursor()
        if except_id:
            cur.execute(
                """
                UPDATE skills SET status = ?, updated_at = ?
                WHERE lower(name) = lower(?) AND status = ? AND skill_id != ?
                """,
                (STATUS_VERIFIED, _utc_now(), name, STATUS_ACTIVE, except_id),
            )
        else:
            cur.execute(
                """
                UPDATE skills SET status = ?, updated_at = ?
                WHERE lower(name) = lower(?) AND status = ?
                """,
                (STATUS_VERIFIED, _utc_now(), name, STATUS_ACTIVE),
            )
        self._conn.commit()

    def start_validation(self, skill_id: str) -> Skill:
        return self.transition(skill_id, STATUS_VALIDATING)

    def mark_verified(self, skill_id: str) -> Skill:
        """Call only after validation_tests have been checked by the caller."""
        skill = self.get(skill_id)
        if not skill:
            raise KeyError(f"Skill not found: {skill_id}")
        if skill.status == STATUS_PROPOSED:
            self.transition(skill_id, STATUS_VALIDATING)
        return self.transition(skill_id, STATUS_VERIFIED)

    def mark_rejected(self, skill_id: str, reason: str = "") -> Skill:
        skill = self.get(skill_id)
        if not skill:
            raise KeyError(f"Skill not found: {skill_id}")
        if reason:
            failures = list(skill.known_failures)
            failures.append(f"Rejected: {reason}")
            skill.known_failures = failures
            skill.updated_at = _utc_now()
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE skills SET known_failures = ?, updated_at = ? WHERE skill_id = ?",
                (_json_dumps(skill.known_failures), skill.updated_at, skill.skill_id),
            )
            self._conn.commit()
        # From any non-REJECTED state that allows it
        if skill.status == STATUS_ACTIVE:
            self.transition(skill_id, STATUS_VERIFIED)
            skill = self.get(skill_id)
        if skill and skill.status != STATUS_REJECTED:
            return self.transition(skill_id, STATUS_REJECTED)
        return skill  # type: ignore

    def activate(self, skill_id: str) -> Skill:
        """Activate a VERIFIED skill. Raises if not verified."""
        skill = self.get(skill_id)
        if not skill:
            raise KeyError(f"Skill not found: {skill_id}")
        if skill.status != STATUS_VERIFIED:
            raise ValueError(
                f"Cannot activate skill in status {skill.status}; must be VERIFIED"
            )
        return self.transition(skill_id, STATUS_ACTIVE)

    def deactivate(self, skill_id: str) -> Skill:
        """ACTIVE → VERIFIED (safe, reversible)."""
        return self.transition(skill_id, STATUS_VERIFIED)

    def _update_status_fields(self, skill: Skill) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE skills SET status = ?, updated_at = ? WHERE skill_id = ?",
            (skill.status, skill.updated_at, skill.skill_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ Versioning
    def create_new_version(
        self,
        skill_id: str,
        **overrides: Any,
    ) -> Skill:
        """Create a PROPOSED new version based on an existing skill.

        Does not replace the active version until the new one is verified + activated.
        """
        parent = self.get(skill_id)
        if not parent:
            raise KeyError(f"Skill not found: {skill_id}")
        data = parent.to_dict()
        data.pop("skill_id", None)
        data["parent_skill_id"] = parent.skill_id
        data["version"] = parent.version + 1
        data["status"] = STATUS_PROPOSED
        data["usage_count"] = 0
        data["created_at"] = ""
        data["updated_at"] = ""
        for k, v in overrides.items():
            if k in data and k not in ("skill_id", "status", "version", "parent_skill_id"):
                data[k] = v
        return self.create_skill(
            name=data["name"],
            description=data.get("description", ""),
            category=data.get("category", "general"),
            when_to_use=data.get("when_to_use", ""),
            prerequisites=data.get("prerequisites"),
            required_tools=data.get("required_tools"),
            procedure=data.get("procedure"),
            examples=data.get("examples"),
            known_failures=data.get("known_failures"),
            successful_patterns=data.get("successful_patterns"),
            validation_tests=data.get("validation_tests"),
            confidence=data.get("confidence", 0.5),
            source_task=data.get("source_task"),
            tags=data.get("tags"),
            parent_skill_id=parent.skill_id,
            version=data["version"],
        )

    def rollback_to_version(self, name: str, version: int) -> Skill:
        """Activate a previously VERIFIED or ACTIVE historical version.

        Target must be VERIFIED or already ACTIVE. Current ACTIVE of same name
        is demoted to VERIFIED.
        """
        matches = [s for s in self.list_by_name(name) if s.version == version]
        if not matches:
            raise KeyError(f"No skill named {name!r} at version {version}")
        target = matches[0]
        if target.status == STATUS_ACTIVE:
            return target
        if target.status not in (STATUS_VERIFIED, STATUS_ACTIVE):
            # Allow rollback only to verified lineage
            if target.status == STATUS_REJECTED:
                raise ValueError("Cannot rollback to a REJECTED skill")
            # If PROPOSED/VALIDATING, refuse
            raise ValueError(
                f"Cannot rollback to status {target.status}; must be VERIFIED"
            )
        return self.activate(target.skill_id)

    # ------------------------------------------------------------------ Usage
    def record_usage(self, skill_id: str) -> Optional[Skill]:
        skill = self.get(skill_id)
        if not skill:
            return None
        skill.usage_count += 1
        skill.updated_at = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE skills SET usage_count = ?, updated_at = ? WHERE skill_id = ?",
            (skill.usage_count, skill.updated_at, skill.skill_id),
        )
        self._conn.commit()
        return skill

    def update_fields(self, skill_id: str, **fields: Any) -> Optional[Skill]:
        skill = self.get(skill_id)
        if not skill:
            return None
        allowed = {
            "description",
            "category",
            "when_to_use",
            "prerequisites",
            "required_tools",
            "procedure",
            "examples",
            "known_failures",
            "successful_patterns",
            "validation_tests",
            "confidence",
            "tags",
            "source_task",
        }
        for k, v in fields.items():
            if k in allowed:
                setattr(skill, k, v)
        skill.updated_at = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE skills SET description=?, category=?, when_to_use=?,
            prerequisites=?, required_tools=?, procedure=?, examples=?,
            known_failures=?, successful_patterns=?, validation_tests=?,
            confidence=?, tags=?, source_task=?, updated_at=?
            WHERE skill_id=?
            """,
            (
                skill.description,
                skill.category,
                skill.when_to_use,
                _json_dumps(skill.prerequisites),
                _json_dumps(skill.required_tools),
                _json_dumps(skill.procedure),
                _json_dumps(skill.examples),
                _json_dumps(skill.known_failures),
                _json_dumps(skill.successful_patterns),
                _json_dumps(skill.validation_tests),
                skill.confidence,
                _json_dumps(skill.tags),
                skill.source_task,
                skill.updated_at,
                skill.skill_id,
            ),
        )
        self._conn.commit()
        return skill

    # ------------------------------------------------------------------ Validation helper
    def run_structural_validation(self, skill_id: str) -> tuple[bool, list[str]]:
        """Lightweight structural checks — not full agent execution.

        Returns (ok, list of failure reasons).
        Does not change status; caller decides transitions.
        """
        skill = self.get(skill_id)
        if not skill:
            return False, ["Skill not found"]
        failures: list[str] = []
        if not skill.name.strip():
            failures.append("Missing name")
        if not skill.procedure:
            failures.append("Procedure is empty")
        for i, step in enumerate(skill.procedure):
            if not isinstance(step, dict):
                failures.append(f"Step {i} is not a structured dict")
            elif not step.get("action") and not step.get("description"):
                failures.append(f"Step {i} lacks action/description")
        # validation_tests may be empty for manual review skills
        return (len(failures) == 0, failures)
