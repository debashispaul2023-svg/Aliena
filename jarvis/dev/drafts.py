"""Reviewable code drafts with hash-bound approval (no code execution)."""
from __future__ import annotations

import ast
import difflib
import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jarvis.dev.sensitive_paths import assert_safe_workspace_path, is_sensitive_relative
from jarvis.dev.workspace import DevWorkspace, WorkspaceError

AUDIT: list[dict] = []
# Legacy constant, not used for enforcement. The single source of truth is
# jarvis.dev.sensitive_paths (kept here only so existing imports do not break).
PROTECTED = {".env", "id_rsa", "id_ed25519"}


def audit_log() -> list[dict]:
    return list(AUDIT)

MAX_DRAFT_FILES = 100
MAX_DRAFT_FILE_BYTES = 1_048_576


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()



def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(project_id: str, files: list[DraftFile]) -> str:
    material = "\n".join(
        f"{f.path}\0{f.original_sha256 or '-'}\0{f.proposed_sha256}"
        for f in files
    )
    return _sha(f"{project_id}\0{material}")


class DraftError(ValueError):
    pass


@dataclass
class DraftFile:
    path: str
    original_sha256: Optional[str]
    proposed_sha256: str
    proposed_content: str
    unified_diff: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DraftApproval:
    draft_id: str
    fingerprint: str
    reviewer: str
    approved_at: str = field(default_factory=_now)


@dataclass
class CodeDraft:
    draft_id: str
    project_id: str
    files: list[DraftFile]
    fingerprint: str
    created_at: str = field(default_factory=_now)
    status: str = "REVIEW_REQUIRED"
    approval: Optional[DraftApproval] = None

    def to_dict(self) -> dict:
        return {
            "draft_id": self.draft_id,
            "project_id": self.project_id,
            "files": [f.to_dict() for f in self.files],
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "status": self.status,
            "approval": asdict(self.approval) if self.approval else None,
        }


def create_code_draft(workspace: DevWorkspace, changes: list, *, project_id: str) -> CodeDraft:
    """Build a review-only draft from FileChange-like objects; writes nothing."""
    if not project_id or not isinstance(project_id, str):
        raise DraftError("project_id is required")
    if not changes:
        raise DraftError("at least one change is required")
    if len(changes) > MAX_DRAFT_FILES:
        raise DraftError(f"draft exceeds {MAX_DRAFT_FILES} files")
    seen: set[str] = set()
    files: list[DraftFile] = []
    for change in changes:
        raw_path = str(getattr(change, "path", ""))
        content = getattr(change, "content", None)
        if not isinstance(content, str) or not content:
            raise DraftError(f"empty or invalid content: {raw_path!r}")
        if len(content.encode("utf-8")) > MAX_DRAFT_FILE_BYTES:
            raise DraftError(f"draft file exceeds {MAX_DRAFT_FILE_BYTES} bytes: {raw_path!r}")
        try:
            target = workspace.resolve(raw_path)
            path = target.relative_to(workspace.project_root).as_posix()
        except (WorkspaceError, ValueError) as exc:
            code = exc.code if isinstance(exc, WorkspaceError) else "path_escape"
            raise DraftError(f"unsafe path {raw_path!r}: {code}") from exc
        if path in seen:
            raise DraftError(f"duplicate path: {path}")
        seen.add(path)
        if target.exists() and not bool(getattr(change, "overwrite", False)):
            raise DraftError(f"overwrite not authorized for existing file: {path}")
        if is_sensitive_relative(path):
            # Contract preserved: a draft for a protected path can still be created and
            # reviewed, but apply_approved_draft always refuses it. The existing file is
            # NEVER read here - a diff over an existing .env would otherwise embed its
            # secret contents in the draft (verified defect, Phase 5).
            note = f"(diff withheld: protected path {path}; this draft can never be applied)\n"
            files.append(DraftFile(path, None, _sha(content), content, note))
            continue
        try:
            original = workspace.read_text(path) if target.is_file() else None
        except UnicodeDecodeError as exc:
            raise DraftError(f"target is not UTF-8 text: {path}") from exc
        before = original.splitlines(keepends=True) if original is not None else []
        after = content.splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}"))
        files.append(DraftFile(path, _sha(original) if original is not None else None, _sha(content), content, diff))
    fingerprint = _fingerprint(project_id, files)
    return CodeDraft(f"draft_{uuid.uuid4().hex[:12]}", project_id, files, fingerprint)


def approve_code_draft(draft: CodeDraft, *, reviewer: str, fingerprint: str) -> DraftApproval:
    """Record explicit review approval, bound to the exact draft fingerprint."""
    if not reviewer or not reviewer.strip():
        raise DraftError("reviewer identity is required")
    if fingerprint != draft.fingerprint or _fingerprint(draft.project_id, draft.files) != draft.fingerprint:
        raise DraftError("draft fingerprint mismatch")
    approval = DraftApproval(draft.draft_id, draft.fingerprint, reviewer.strip())
    draft.approval = approval
    draft.status = "APPROVED"
    return approval


def apply_approved_draft(workspace: DevWorkspace, draft: CodeDraft, approval: Optional[DraftApproval] = None) -> list[str]:
    """Apply only an approved, unchanged draft; generated code is never run."""
    approval = approval or draft.approval
    if draft.status != "APPROVED" or approval is None:
        raise DraftError("approval_required")
    if approval.draft_id != draft.draft_id or approval.fingerprint != draft.fingerprint:
        raise DraftError("approval_does_not_match_draft")
    if _fingerprint(draft.project_id, draft.files) != draft.fingerprint:
        raise DraftError("draft_manifest_tampered_after_approval")
    # Validate every path and baseline before writing any file.
    targets = []
    for item in draft.files:
        if is_sensitive_relative(item.path):
            # Refuse before touching the file: protected content is never read or compared.
            AUDIT.append({"action": "reject", "path": item.path, "draft_id": draft.draft_id, "reason": "protected_or_unsafe"})
            raise DraftError(f"protected path: {item.path}")
        target = workspace.resolve(item.path)
        try:
            current = workspace.read_text(item.path) if target.is_file() else None
        except UnicodeDecodeError as exc:
            raise DraftError(f"target is not UTF-8 text: {item.path}") from exc
        if target.exists() and not target.is_file():
            raise DraftError(f"target is not a regular file: {item.path}")
        current_hash = _sha(current) if current is not None else None
        if current_hash != item.original_sha256:
            raise DraftError(f"workspace_changed_since_review: {item.path}")
        if _sha(item.proposed_content) != item.proposed_sha256:
            raise DraftError(f"draft_content_changed: {item.path}")
        targets.append(item)
    written = []
    backups: list[tuple[str, Optional[str]]] = []
    try:
        for item in targets:
            try:
                assert_safe_workspace_path(workspace.project_root, item.path)
            except ValueError as exc:
                AUDIT.append({"action": "reject", "path": item.path, "draft_id": draft.draft_id, "reason": "protected_or_unsafe"})
                raise DraftError(f"protected path: {item.path}") from exc
            # Recheck immediately before write. This reduces the window; it does not prove TOCTOU safety.
            try:
                assert_safe_workspace_path(workspace.project_root, item.path)
            except ValueError as exc:
                AUDIT.append({"action": "reject", "path": item.path, "draft_id": draft.draft_id, "reason": "protected_or_unsafe"})
                raise DraftError(f"protected path: {item.path}") from exc
            if item.path.endswith(".py"):
                try:
                    ast.parse(item.proposed_content)
                except SyntaxError as exc:
                    raise DraftError(f"syntax error in {item.path}: {exc}") from exc
            target = workspace.resolve(item.path)
            previous = workspace.read_text(item.path) if target.is_file() else None
            backups.append((item.path, previous))
            workspace.write_text(item.path, item.proposed_content, overwrite=item.original_sha256 is not None)
            written.append(item.path)
            AUDIT.append({"action": "apply", "path": item.path, "draft_id": draft.draft_id})
    except Exception:
        for path, previous in reversed(backups):
            if previous is None:
                try:
                    workspace.resolve(path).unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                workspace.write_text(path, previous, overwrite=True)
            AUDIT.append({"action": "rollback", "path": path, "draft_id": draft.draft_id})
        raise
    draft.status = "APPLIED"
    return written
