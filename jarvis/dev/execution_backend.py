"""Phase 6F offline preparation. Does not execute code or call external services.

Statuses describe application state only. MOCKED does not prove isolation.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Optional
from jarvis.dev.sensitive_paths import is_sensitive_relative

STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_BLOCKED = "BLOCKED"
STATUS_MOCKED = "MOCKED"
STATUS_EXECUTED = "EXECUTED"

ALLOWED_SUFFIXES = {".py", ".md", ".txt"}
PROTECTED_NAMES = {
    "jarvis_memory.db",
    "jarvis_skills.db",
    "jarvis_resources.db",
    ".env",
    "id_rsa",
    "id_ed25519",
}
MAX_BYTES = 256 * 1024


class ArtifactError(ValueError):
    """Invalid artifact manifest."""


@dataclass
class ArtifactEntry:
    path: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactManifest:
    manifest_id: str
    files: list[ArtifactEntry] = field(default_factory=list)

    def fingerprint(self) -> str:
        raw = "|".join(f"{f.path}:{f.sha256}:{f.size}" for f in self.files)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "files": [f.to_dict() for f in self.files],
            "fingerprint": self.fingerprint(),
        }


@dataclass
class Approval:
    manifest_fingerprint: str
    backend: str
    approved: bool = False


@dataclass
class ExecutionRequest:
    backend: str
    manifest: ArtifactManifest
    approval: Optional[Approval] = None
    credentials_present: bool = False


@dataclass
class ExecutionResult:
    status: str
    backend: str
    code_executed: bool = False
    exit_code: Optional[int] = None
    reason: str = ""
    notes: str = "Mock/offline only. Does not prove sandbox isolation."

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_artifact_path(path: str) -> None:
    if not path or path.strip() != path:
        raise ArtifactError("path is empty or padded")
    if path.startswith("/") or ".." in path.split("/") or "\\" in path:
        raise ArtifactError(f"unsafe path: {path}")
    name = path.rsplit("/", 1)[-1]
    if name in PROTECTED_NAMES or name.endswith(".env") or name.endswith(".pem"):
        raise ArtifactError(f"protected file rejected: {name}")
    if is_sensitive_relative(path):  # shared policy (stricter only): e.g. .env.txt, Windows-name variants
        raise ArtifactError(f"protected file rejected: {name}")
    if not any(path.endswith(suf) for suf in ALLOWED_SUFFIXES):
        raise ArtifactError(f"unexpected file type: {path}")
    if path.endswith(".db"):
        raise ArtifactError("database files are not allowed")


def build_manifest(files: list[dict[str, Any]], *, manifest_id: str) -> ArtifactManifest:
    entries: list[ArtifactEntry] = []
    seen: set[str] = set()
    for item in files:
        path = str(item.get("path") or "")
        validate_artifact_path(path)
        if path in seen:
            raise ArtifactError(f"duplicate path: {path}")
        seen.add(path)
        content = item.get("content")
        if not isinstance(content, str):
            raise ArtifactError(f"content required for {path}")
        raw = content.encode("utf-8")
        if len(raw) > MAX_BYTES:
            raise ArtifactError(f"oversized artifact: {path}")
        entries.append(
            ArtifactEntry(
                path=path,
                sha256=hashlib.sha256(raw).hexdigest(),
                size=len(raw),
            )
        )
    return ArtifactManifest(manifest_id=manifest_id, files=entries)


def request_execution(req: ExecutionRequest) -> ExecutionResult:
    """Fail-closed. Never executes code and never calls an external service."""
    if req.backend not in {"xai_code_execution", "grok_build_strict", "mock"}:
        return ExecutionResult(
            status=STATUS_UNAVAILABLE,
            backend=req.backend,
            reason="unknown_backend",
        )
    if req.backend != "mock":
        return ExecutionResult(
            status=STATUS_BLOCKED,
            backend=req.backend,
            reason="isolation_unavailable",
            notes="Real backends are not callable. No external call was made.",
        )
    if req.approval is None or not req.approval.approved:
        return ExecutionResult(
            status=STATUS_BLOCKED,
            backend=req.backend,
            reason="approval_missing",
        )
    if req.approval.backend != req.backend:
        return ExecutionResult(
            status=STATUS_BLOCKED,
            backend=req.backend,
            reason="approval_backend_mismatch",
        )
    if req.approval.manifest_fingerprint != req.manifest.fingerprint():
        return ExecutionResult(
            status=STATUS_BLOCKED,
            backend=req.backend,
            reason="manifest_changed",
        )
    return ExecutionResult(
        status=STATUS_MOCKED,
        backend=req.backend,
        code_executed=False,
        reason="mock_only",
        notes="MOCKED verifies application logic only. Not real execution.",
    )
