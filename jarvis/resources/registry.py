"""Persistent Resource Registry (Phase D).

Tracks discovered and downloaded resources with provenance, integrity,
and lifecycle status. Separate SQLite database from memory/skills.

Does not download, install, extract, or execute resources.
Does not store secrets.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from jarvis.resources.downloader import DownloadResult, VerificationResult, verify_file

# Lifecycle states
STATUS_DISCOVERED = "DISCOVERED"
STATUS_EVALUATING = "EVALUATING"
STATUS_AWAITING_APPROVAL = "AWAITING_APPROVAL"
STATUS_DOWNLOADING = "DOWNLOADING"
STATUS_VERIFYING = "VERIFYING"
STATUS_VERIFIED = "VERIFIED"
STATUS_FAILED = "FAILED"
STATUS_CANCELLED = "CANCELLED"
STATUS_QUARANTINED = "QUARANTINED"
STATUS_REJECTED = "REJECTED"

ALL_STATUSES = {
    STATUS_DISCOVERED,
    STATUS_EVALUATING,
    STATUS_AWAITING_APPROVAL,
    STATUS_DOWNLOADING,
    STATUS_VERIFYING,
    STATUS_VERIFIED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_QUARANTINED,
    STATUS_REJECTED,
}

# Allowed transitions (from → set of to)
_TRANSITIONS: dict[str, set[str]] = {
    STATUS_DISCOVERED: {
        STATUS_EVALUATING,
        STATUS_AWAITING_APPROVAL,
        STATUS_DOWNLOADING,
        STATUS_REJECTED,
        STATUS_CANCELLED,
        STATUS_FAILED,
    },
    STATUS_EVALUATING: {
        STATUS_AWAITING_APPROVAL,
        STATUS_DOWNLOADING,
        STATUS_REJECTED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    },
    STATUS_AWAITING_APPROVAL: {
        STATUS_DOWNLOADING,
        STATUS_REJECTED,
        STATUS_CANCELLED,
    },
    STATUS_DOWNLOADING: {
        STATUS_VERIFYING,
        STATUS_FAILED,
        STATUS_CANCELLED,
        STATUS_QUARANTINED,
    },
    STATUS_VERIFYING: {
        STATUS_VERIFIED,
        STATUS_FAILED,
        STATUS_QUARANTINED,
        STATUS_CANCELLED,
    },
    STATUS_VERIFIED: {
        STATUS_QUARANTINED,
        STATUS_FAILED,  # e.g. recheck found drift
        STATUS_DOWNLOADING,  # re-download with approval
    },
    STATUS_FAILED: {
        STATUS_DISCOVERED,
        STATUS_DOWNLOADING,
        STATUS_REJECTED,
        STATUS_CANCELLED,
    },
    STATUS_CANCELLED: {
        STATUS_DISCOVERED,
        STATUS_DOWNLOADING,
    },
    STATUS_QUARANTINED: {
        STATUS_REJECTED,
        STATUS_FAILED,
        STATUS_DISCOVERED,
    },
    STATUS_REJECTED: set(),  # terminal unless re-discovered as new id
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class ResourceRecord:
    id: str
    title: str
    status: str
    source: str = ""
    kind: str = "unknown"
    category: str = ""
    original_url: str = ""
    canonical_url: str = ""
    description: str = ""
    version: Optional[str] = None
    license: Optional[str] = None
    project: Optional[str] = None
    local_path: Optional[str] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    expected_sha256: Optional[str] = None
    verification_status: Optional[str] = None  # e.g. ok | mismatch | missing | unknown
    authenticity_verified: bool = False
    created_at: str = ""
    updated_at: str = ""
    downloaded_at: Optional[str] = None
    error: Optional[str] = None
    warning: Optional[str] = None
    compatibility: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class RegistryError(Exception):
    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ResourceRegistry:
    """SQLite-backed registry for resource lifecycle tracking."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    kind TEXT DEFAULT 'unknown',
                    category TEXT DEFAULT '',
                    original_url TEXT DEFAULT '',
                    canonical_url TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    version TEXT,
                    license TEXT,
                    project TEXT,
                    local_path TEXT,
                    size INTEGER,
                    sha256 TEXT,
                    expected_sha256 TEXT,
                    verification_status TEXT,
                    authenticity_verified INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    downloaded_at TEXT,
                    error TEXT,
                    warning TEXT,
                    compatibility_json TEXT DEFAULT '{}',
                    metadata_json TEXT DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_source ON resources(source)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_project ON resources(project)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_url ON resources(canonical_url)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_sha ON resources(sha256)"
            )
            conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> ResourceRecord:
        return ResourceRecord(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            source=row["source"] or "",
            kind=row["kind"] or "unknown",
            category=row["category"] or "",
            original_url=row["original_url"] or "",
            canonical_url=row["canonical_url"] or "",
            description=row["description"] or "",
            version=row["version"],
            license=row["license"],
            project=row["project"],
            local_path=row["local_path"],
            size=row["size"],
            sha256=row["sha256"],
            expected_sha256=row["expected_sha256"],
            verification_status=row["verification_status"],
            authenticity_verified=bool(row["authenticity_verified"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            downloaded_at=row["downloaded_at"],
            error=row["error"],
            warning=row["warning"],
            compatibility=json.loads(row["compatibility_json"] or "{}"),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_discovered(
        self,
        *,
        title: str,
        url: str = "",
        source: str = "",
        kind: str = "unknown",
        category: str = "",
        description: str = "",
        version: Optional[str] = None,
        license: Optional[str] = None,
        project: Optional[str] = None,
        compatibility: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        allow_duplicate: bool = False,
    ) -> ResourceRecord:
        """Register a search result. Does not download."""
        title = (title or "").strip() or (url or "unnamed")
        canonical = (url or "").strip()
        if not allow_duplicate and canonical:
            existing = self.find_by_url(canonical, source=source or None)
            if existing:
                return existing

        rid = _new_id()
        now = _utcnow()
        rec = ResourceRecord(
            id=rid,
            title=title,
            status=STATUS_DISCOVERED,
            source=source or "",
            kind=kind or "unknown",
            category=category or "",
            original_url=canonical,
            canonical_url=canonical,
            description=description or "",
            version=version,
            license=license,
            project=project,
            created_at=now,
            updated_at=now,
            compatibility=compatibility or {},
            metadata=self._sanitize_meta(metadata or {}),
        )
        self._insert(rec)
        return rec

    def register_download(
        self,
        download: DownloadResult,
        *,
        title: Optional[str] = None,
        source: str = "",
        kind: str = "unknown",
        category: str = "",
        project: Optional[str] = None,
        expected_sha256: Optional[str] = None,
        resource_id: Optional[str] = None,
        version: Optional[str] = None,
        license: Optional[str] = None,
    ) -> ResourceRecord:
        """Create or update a record from a DownloadResult.

        VERIFIED only when download.success and verification evidence is ok.
        """
        now = _utcnow()
        url = download.final_url or download.original_url or ""
        title = title or (Path(download.path).name if download.path else url) or "download"

        # Prefer updating existing resource_id or URL match
        existing: Optional[ResourceRecord] = None
        if resource_id:
            existing = self.get(resource_id)
        if existing is None and url:
            existing = self.find_by_url(url, source=source or None)
        if existing is None and download.sha256:
            existing = self.find_by_sha256(download.sha256)

        if not download.success:
            status = STATUS_CANCELLED if download.cancelled else STATUS_FAILED
            if existing:
                return self.update_status(
                    existing.id,
                    status,
                    error=download.error,
                    extra={
                        "original_url": download.original_url,
                        "canonical_url": download.final_url or download.original_url,
                    },
                )
            rid = _new_id()
            rec = ResourceRecord(
                id=rid,
                title=title,
                status=status,
                source=source,
                kind=kind,
                category=category,
                original_url=download.original_url,
                canonical_url=url,
                project=project,
                version=version,
                license=license,
                created_at=now,
                updated_at=now,
                error=download.error,
                metadata={"error_code": download.error_code},
            )
            self._insert(rec)
            return rec

        # Successful download → VERIFYING then VERIFIED if checks pass
        authenticity = bool(
            (download.metadata or {}).get("authenticity_verified")
        ) or (
            bool(expected_sha256)
            and bool(download.sha256)
            and expected_sha256.lower() == download.sha256.lower()
        )
        verification_status = "ok"
        if expected_sha256 and download.sha256 and expected_sha256.lower() != download.sha256.lower():
            # Should not happen if downloader enforced it, but record failure
            if existing:
                return self.update_status(
                    existing.id,
                    STATUS_FAILED,
                    error="checksum mismatch after download",
                )
            raise RegistryError("checksum mismatch", code="checksum")

        status = STATUS_VERIFIED
        rid = existing.id if existing else _new_id()
        fields = {
            "id": rid,
            "title": title if not existing else existing.title or title,
            "status": status,
            "source": source or (existing.source if existing else ""),
            "kind": kind or (existing.kind if existing else "unknown"),
            "category": category or (existing.category if existing else ""),
            "original_url": download.original_url or (existing.original_url if existing else ""),
            "canonical_url": url or (existing.canonical_url if existing else ""),
            "description": existing.description if existing else "",
            "version": version if version is not None else (existing.version if existing else None),
            "license": license if license is not None else (existing.license if existing else None),
            "project": project if project is not None else (existing.project if existing else None),
            "local_path": download.path,
            "size": download.size,
            "sha256": download.sha256,
            "expected_sha256": expected_sha256 or (existing.expected_sha256 if existing else None),
            "verification_status": verification_status,
            "authenticity_verified": 1 if authenticity else 0,
            "created_at": existing.created_at if existing else now,
            "updated_at": now,
            "downloaded_at": now,
            "error": None,
            "warning": None,
            "compatibility_json": json.dumps(
                existing.compatibility if existing else {}
            ),
            "metadata_json": json.dumps(
                self._sanitize_meta(
                    {
                        **(existing.metadata if existing else {}),
                        "content_type": download.content_type,
                    }
                )
            ),
        }
        with self._connect() as conn:
            if existing:
                conn.execute(
                    """
                    UPDATE resources SET
                        title=?, status=?, source=?, kind=?, category=?,
                        original_url=?, canonical_url=?, version=?, license=?,
                        project=?, local_path=?, size=?, sha256=?, expected_sha256=?,
                        verification_status=?, authenticity_verified=?,
                        updated_at=?, downloaded_at=?, error=NULL, warning=NULL,
                        metadata_json=?
                    WHERE id=?
                    """,
                    (
                        fields["title"],
                        fields["status"],
                        fields["source"],
                        fields["kind"],
                        fields["category"],
                        fields["original_url"],
                        fields["canonical_url"],
                        fields["version"],
                        fields["license"],
                        fields["project"],
                        fields["local_path"],
                        fields["size"],
                        fields["sha256"],
                        fields["expected_sha256"],
                        fields["verification_status"],
                        fields["authenticity_verified"],
                        fields["updated_at"],
                        fields["downloaded_at"],
                        fields["metadata_json"],
                        rid,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO resources (
                        id, title, status, source, kind, category,
                        original_url, canonical_url, description, version, license,
                        project, local_path, size, sha256, expected_sha256,
                        verification_status, authenticity_verified,
                        created_at, updated_at, downloaded_at, error, warning,
                        compatibility_json, metadata_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fields["id"],
                        fields["title"],
                        fields["status"],
                        fields["source"],
                        fields["kind"],
                        fields["category"],
                        fields["original_url"],
                        fields["canonical_url"],
                        "",
                        fields["version"],
                        fields["license"],
                        fields["project"],
                        fields["local_path"],
                        fields["size"],
                        fields["sha256"],
                        fields["expected_sha256"],
                        fields["verification_status"],
                        fields["authenticity_verified"],
                        fields["created_at"],
                        fields["updated_at"],
                        fields["downloaded_at"],
                        None,
                        None,
                        fields["compatibility_json"],
                        fields["metadata_json"],
                    ),
                )
            conn.commit()
        return self.get(rid)  # type: ignore

    def _insert(self, rec: ResourceRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resources (
                    id, title, status, source, kind, category,
                    original_url, canonical_url, description, version, license,
                    project, local_path, size, sha256, expected_sha256,
                    verification_status, authenticity_verified,
                    created_at, updated_at, downloaded_at, error, warning,
                    compatibility_json, metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rec.id,
                    rec.title,
                    rec.status,
                    rec.source,
                    rec.kind,
                    rec.category,
                    rec.original_url,
                    rec.canonical_url,
                    rec.description,
                    rec.version,
                    rec.license,
                    rec.project,
                    rec.local_path,
                    rec.size,
                    rec.sha256,
                    rec.expected_sha256,
                    rec.verification_status,
                    1 if rec.authenticity_verified else 0,
                    rec.created_at,
                    rec.updated_at,
                    rec.downloaded_at,
                    rec.error,
                    rec.warning,
                    json.dumps(rec.compatibility or {}),
                    json.dumps(self._sanitize_meta(rec.metadata or {})),
                ),
            )
            conn.commit()

    @staticmethod
    def _sanitize_meta(meta: dict[str, Any]) -> dict[str, Any]:
        """Strip keys that look like secrets."""
        blocked = {
            "token",
            "api_key",
            "apikey",
            "password",
            "secret",
            "authorization",
            "access_token",
            "refresh_token",
        }
        out: dict[str, Any] = {}
        for k, v in meta.items():
            if k.lower() in blocked or any(b in k.lower() for b in blocked):
                continue
            out[k] = v
        return out

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------

    def update_status(
        self,
        resource_id: str,
        new_status: str,
        *,
        error: Optional[str] = None,
        warning: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
        force: bool = False,
    ) -> ResourceRecord:
        if new_status not in ALL_STATUSES:
            raise RegistryError(f"Unknown status: {new_status}", code="bad_status")
        rec = self.get(resource_id)
        if rec is None:
            raise RegistryError(f"Unknown resource: {resource_id}", code="not_found")
        if not force and new_status not in _TRANSITIONS.get(rec.status, set()):
            raise RegistryError(
                f"Invalid transition {rec.status} → {new_status}",
                code="bad_transition",
            )
        # VERIFIED requires local evidence
        if new_status == STATUS_VERIFIED:
            if not rec.local_path or not rec.sha256:
                raise RegistryError(
                    "Cannot mark VERIFIED without local_path and sha256",
                    code="verify_required",
                )
            if rec.local_path and not Path(rec.local_path).is_file():
                raise RegistryError(
                    "Cannot mark VERIFIED: local file missing",
                    code="verify_required",
                )

        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE resources SET status=?, error=?, warning=?, updated_at=?
                WHERE id=?
                """,
                (new_status, error if error is not None else rec.error, warning, now, resource_id),
            )
            if extra:
                # limited safe field updates
                for key in ("original_url", "canonical_url", "local_path", "version"):
                    if key in extra and extra[key] is not None:
                        conn.execute(
                            f"UPDATE resources SET {key}=? WHERE id=?",  # noqa: S608 — key whitelist
                            (extra[key], resource_id),
                        )
            conn.commit()
        return self.get(resource_id)  # type: ignore

    def record_verification(
        self,
        resource_id: str,
        result: VerificationResult,
    ) -> ResourceRecord:
        """Apply a VerificationResult; may move to VERIFIED or FAILED."""
        rec = self.get(resource_id)
        if rec is None:
            raise RegistryError(f"Unknown resource: {resource_id}", code="not_found")
        now = _utcnow()
        if result.ok:
            new_status = STATUS_VERIFIED
            vstatus = "ok"
        else:
            new_status = STATUS_FAILED if rec.status in {
                STATUS_VERIFYING, STATUS_DOWNLOADING, STATUS_VERIFIED
            } else rec.status
            vstatus = "failed"
            if not result.exists:
                vstatus = "missing"
            elif result.checksum_match is False:
                vstatus = "mismatch"

        # Do not silently update stored sha256 when mismatch
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE resources SET
                    status=?,
                    verification_status=?,
                    authenticity_verified=?,
                    size=?,
                    updated_at=?,
                    error=?,
                    warning=?
                WHERE id=?
                """,
                (
                    new_status if (
                        new_status in _TRANSITIONS.get(rec.status, set())
                        or new_status == rec.status
                        or (rec.status == STATUS_VERIFIED and new_status == STATUS_FAILED)
                    ) else rec.status,
                    vstatus,
                    1 if result.authenticity_verified else 0,
                    result.size if result.exists else rec.size,
                    now,
                    "; ".join(result.errors) if result.errors else None,
                    result.notes,
                    resource_id,
                ),
            )
            # Update sha256 only when verification ok and we have a digest
            if result.ok and result.sha256:
                conn.execute(
                    "UPDATE resources SET sha256=? WHERE id=?",
                    (result.sha256, resource_id),
                )
            conn.commit()
        return self.get(resource_id)  # type: ignore

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, resource_id: str) -> Optional[ResourceRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM resources WHERE id=?", (resource_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def find_by_url(
        self, url: str, *, source: Optional[str] = None
    ) -> Optional[ResourceRecord]:
        url = (url or "").strip()
        if not url:
            return None
        with self._connect() as conn:
            if source:
                row = conn.execute(
                    """
                    SELECT * FROM resources
                    WHERE (canonical_url=? OR original_url=?) AND source=?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (url, url, source),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM resources
                    WHERE canonical_url=? OR original_url=?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (url, url),
                ).fetchone()
        return self._row_to_record(row) if row else None

    def find_by_sha256(self, sha256: str) -> Optional[ResourceRecord]:
        if not sha256:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM resources WHERE lower(sha256)=lower(?)
                ORDER BY updated_at DESC LIMIT 1
                """,
                (sha256,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list(
        self,
        *,
        status: Optional[str] = None,
        source: Optional[str] = None,
        project: Optional[str] = None,
        category: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> list[ResourceRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if source:
            clauses.append("source=?")
            params.append(source)
        if project:
            clauses.append("project=?")
            params.append(project)
        if category:
            clauses.append("category=?")
            params.append(category)
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM resources{where} ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def search(self, query: str, *, limit: int = 50) -> list[ResourceRecord]:
        q = f"%{(query or '').strip()}%"
        if q == "%%":
            return self.list(limit=limit)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM resources
                WHERE title LIKE ? OR description LIKE ? OR canonical_url LIKE ?
                   OR original_url LIKE ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (q, q, q, q, max(1, int(limit))),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    # ------------------------------------------------------------------
    # Recheck & manifest
    # ------------------------------------------------------------------

    def recheck(self, resource_id: str) -> ResourceRecord:
        """Re-verify local file against recorded checksum/size. Does not rewrite identity on mismatch."""
        rec = self.get(resource_id)
        if rec is None:
            raise RegistryError(f"Unknown resource: {resource_id}", code="not_found")
        if not rec.local_path:
            return self.update_status(
                resource_id,
                STATUS_FAILED if rec.status == STATUS_VERIFIED else rec.status,
                error="No local_path to recheck",
                force=True,
            )

        vr = verify_file(
            rec.local_path,
            expected_sha256=rec.sha256,
            expected_size=rec.size,
            require_nonzero=True,
        )
        return self.record_verification(resource_id, vr)

    def export_manifest(
        self,
        *,
        project: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        """Safe JSON-serializable manifest (no secrets)."""
        rows = self.list(project=project, status=status, limit=10_000)
        return {
            "schema": "jarvis.resource_manifest.v1",
            "exported_at": _utcnow(),
            "count": len(rows),
            "resources": [
                {
                    "id": r.id,
                    "title": r.title,
                    "status": r.status,
                    "source": r.source,
                    "kind": r.kind,
                    "category": r.category,
                    "canonical_url": r.canonical_url,
                    "original_url": r.original_url,
                    "version": r.version,
                    "license": r.license,
                    "project": r.project,
                    "local_path": r.local_path,
                    "size": r.size,
                    "sha256": r.sha256,
                    "verification_status": r.verification_status,
                    "authenticity_verified": r.authenticity_verified,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                    "downloaded_at": r.downloaded_at,
                    "error": r.error,
                    # metadata already sanitized on write
                    "metadata": self._sanitize_meta(r.metadata),
                }
                for r in rows
            ],
        }

    def export_manifest_json(
        self,
        path: str | Path,
        *,
        project: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Path:
        path = Path(path)
        data = self.export_manifest(project=project, status=status)
        path.write_text(json.dumps(data, indent=2, sort_keys=False))
        return path
