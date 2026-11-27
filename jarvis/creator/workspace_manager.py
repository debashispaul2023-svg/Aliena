"""Isolated Creator workspaces (C2).

Each project lives in <root>/<project_id>/ with a private ``.creator/`` control dir
(project.json, manifest.json, history.jsonl, checkpoints/). All paths are resolved
against that project root only; every mutation is routed through SecurityGate.
Nothing here executes generated code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jarvis.core.approval import ApprovalDecision
from jarvis.creator.audit import AuditLogger
from jarvis.creator.security_gate import SecurityGate
from jarvis.dev.sensitive_paths import is_sensitive_relative
from jarvis.dev.workspace import WorkspaceError, validate_project_name

CONTROL_DIR = ".creator"
SCHEMA_VERSION = 1
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 2000
MAX_PATH_LEN = 240
_PID = re.compile(r"^cre_[0-9a-f]{16}$")
_CKPT = re.compile(r"^ckpt_\d{4}$")
_WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class CreatorWorkspaceError(WorkspaceError):
    pass


class PathViolation(CreatorWorkspaceError):
    pass


class CollisionError(CreatorWorkspaceError):
    pass


class ApprovalRequired(CreatorWorkspaceError):
    pass


class UnknownProject(CreatorWorkspaceError):
    pass


def check_relative_path(rel: str) -> list[str]:
    """Pure lexical validation of a workspace-relative path. Returns its segments."""
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        raise PathViolation("empty or invalid path")
    if len(rel) > MAX_PATH_LEN:
        raise PathViolation("path too long")
    norm = rel.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or norm.startswith("~"):
        raise PathViolation("absolute paths are not allowed")
    parts = norm.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise PathViolation("empty, '.' or '..' path segment")
        if part != part.strip() or part.endswith("."):
            raise PathViolation("unsafe path segment")
        if part.split(".")[0].lower() in _WIN_RESERVED:
            raise PathViolation("reserved device name")
        if ":" in part:
            raise PathViolation("unsafe character in path")
    if parts[0].lower() == CONTROL_DIR:
        raise PathViolation("control directory is reserved")
    if is_sensitive_relative(norm):
        raise PathViolation("sensitive file name is not allowed")
    return parts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(target: Path, data: bytes) -> None:
    """Write temp file in the same directory, fsync, then os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class CreatorWorkspaceManager:
    def __init__(self, root: Path, gate: SecurityGate, audit: Optional[AuditLogger] = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.gate = gate
        self.audit = audit or AuditLogger()
        self._lock = threading.RLock()

    # ---------- project lifecycle ----------
    def create_project(self, name: str, project_type: str = "unknown", actor: str = "creator") -> str:
        name = validate_project_name(name)
        pid = "cre_" + uuid.uuid4().hex[:16]
        d = self.gate.check(pid, actor, "create_workspace")
        if not d.allowed:
            raise ApprovalRequired(d.reason)
        with self._lock:
            pdir = self.root / pid
            if pdir.exists():  # uuid collision: refuse, never reuse
                raise CollisionError("project directory already exists")
            (pdir / CONTROL_DIR / "checkpoints").mkdir(parents=True)
            meta = {"schema_version": SCHEMA_VERSION, "project_id": pid, "name": name,
                    "project_type": project_type, "created_at": _now(), "state": "created"}
            _atomic_write(pdir / CONTROL_DIR / "project.json", json.dumps(meta, indent=2).encode())
            self._save_manifest(pid, {})
            self._history(pid, actor, "create_project", name)
        return pid

    def list_projects(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and _PID.match(p.name))

    def metadata(self, pid: str) -> dict[str, Any]:
        return json.loads((self._pdir(pid) / CONTROL_DIR / "project.json").read_text("utf-8"))

    # ---------- path safety ----------
    def _pdir(self, pid: str) -> Path:
        if not isinstance(pid, str) or not _PID.match(pid):
            raise UnknownProject("invalid project id")
        pdir = self.root / pid
        if not pdir.is_dir() or pdir.is_symlink():
            raise UnknownProject("unknown project")
        return pdir

    def resolve_path(self, pid: str, rel: str, actor: str = "creator") -> Path:
        pdir = self._pdir(pid)
        try:
            return self._resolve(pdir, rel)
        except PathViolation as exc:
            self.gate.check(pid, actor, "workspace_escape")
            self.audit.record(pid, actor, "path_violation", "denied", str(exc))
            raise

    @staticmethod
    def _resolve(pdir: Path, rel: str) -> Path:
        parts = check_relative_path(rel)
        target = pdir.joinpath(*parts)
        # reject symlinks at any component (checked without following)
        cur = pdir
        for part in parts:
            cur = cur / part
            if cur.is_symlink():
                raise PathViolation("symlinks are not allowed")
        resolved = target.resolve()
        if os.path.commonpath([str(pdir.resolve()), str(resolved)]) != str(pdir.resolve()):
            raise PathViolation("path escapes workspace")
        return target

    # ---------- manifest / history ----------
    def _manifest_path(self, pid: str) -> Path:
        return self.root / pid / CONTROL_DIR / "manifest.json"

    def manifest(self, pid: str) -> dict[str, dict[str, Any]]:
        self._pdir(pid)
        return json.loads(self._manifest_path(pid).read_text("utf-8"))["files"]

    def _save_manifest(self, pid: str, files: dict[str, dict[str, Any]]) -> None:
        body = {"schema_version": SCHEMA_VERSION, "project_id": pid, "updated_at": _now(), "files": files}
        _atomic_write(self._manifest_path(pid), json.dumps(body, indent=2, sort_keys=True).encode())

    def _history(self, pid: str, actor: str, action: str, detail: str = "") -> None:
        rec = {"ts": _now(), "actor": actor, "action": action, "detail": detail[:300]}
        with (self.root / pid / CONTROL_DIR / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        self.audit.record(pid, actor, action, "ok", detail)

    def history(self, pid: str) -> list[dict[str, Any]]:
        p = self._pdir(pid) / CONTROL_DIR / "history.jsonl"
        return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()] if p.exists() else []

    def inventory(self, pid: str) -> list[dict[str, Any]]:
        return [{"path": k, **v} for k, v in sorted(self.manifest(pid).items())]

    # ---------- file operations ----------
    def _require(self, pid: str, actor: str, action: str, approval: Optional[ApprovalDecision]) -> None:
        d = self.gate.check(pid, actor, action, approval)
        if not d.allowed:
            raise ApprovalRequired(f"{action}: {d.reason}")

    def read_file(self, pid: str, rel: str) -> bytes:
        target = self.resolve_path(pid, rel)
        if not target.is_file():
            raise CreatorWorkspaceError("file not found")
        return target.read_bytes()

    def write_file(self, pid: str, rel: str, content: str | bytes, *, actor: str = "creator",
                   overwrite: bool = False, approval: Optional[ApprovalDecision] = None,
                   op: Optional[str] = None) -> dict[str, Any]:
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(data) > MAX_FILE_BYTES:
            raise CreatorWorkspaceError("file exceeds size limit")
        self._require(pid, actor, "write_generated_file", None)
        with self._lock:
            target = self.resolve_path(pid, rel, actor)
            files = self.manifest(pid)
            key = rel.replace("\\", "/")
            lowered = {k.lower(): k for k in files}
            if lowered.get(key.lower(), key) != key:
                raise CollisionError("case-variant of an existing tracked file")
            exists = target.exists() or (os.path.lexists(target))
            if exists:
                if target.is_dir():
                    raise CollisionError("a directory exists at this path")
                if not overwrite:
                    raise CollisionError("file exists; overwrite not requested")
                self._require(pid, actor, "overwrite_file", approval)  # user-owned or generated: always approval
                self._backup(pid, key, target)
            elif len(files) >= MAX_FILES:
                raise CreatorWorkspaceError("file count limit reached")
            try:
                _atomic_write(target, data)
            except (NotADirectoryError, FileExistsError) as exc:
                raise CollisionError("a parent path component is an existing file") from exc
            files[key] = {"sha256": _sha(data), "size": len(data), "origin": "generated", "updated_at": _now()}
            if op:
                files[key]["op"] = op
            self._save_manifest(pid, files)
            self._history(pid, actor, "overwrite_file" if exists else "write_file", key)
            return {"path": key, **files[key]}

    def delete_file(self, pid: str, rel: str, *, actor: str = "creator",
                    approval: Optional[ApprovalDecision] = None) -> None:
        self._require(pid, actor, "delete_file", approval)
        with self._lock:
            target = self.resolve_path(pid, rel, actor)
            key = rel.replace("\\", "/")
            files = self.manifest(pid)
            if key not in files:
                raise CreatorWorkspaceError("only tracked generated files can be deleted")
            if target.is_file():
                self._backup(pid, key, target)
                target.unlink()
            files.pop(key)
            self._save_manifest(pid, files)
            self._history(pid, actor, "delete_file", key)

    def discard_created(self, pid: str, op: str, *, actor: str = "creator") -> list[str]:
        """Undo files created by one in-flight operation (identified by its private op token).
        Only unmodified tracked files stamped with that token are removed; backed up first."""
        if not isinstance(op, str) or len(op) < 16:
            raise CreatorWorkspaceError("invalid operation token")
        self._require(pid, actor, "discard_generation_output", None)
        with self._lock:
            files = self.manifest(pid)
            removed = []
            for key, meta in list(files.items()):
                if meta.get("op") != op:
                    continue
                t = self.resolve_path(pid, key, actor)
                if t.is_file() and _sha(t.read_bytes()) == meta["sha256"]:
                    self._backup(pid, key, t)
                    t.unlink()
                    files.pop(key)
                    removed.append(key)
            self._save_manifest(pid, files)
            self._history(pid, actor, "discard_created", f"{len(removed)} files")
            return sorted(removed)

    def correct_generated_file(self, pid: str, rel: str, content: str, *, actor: str = "debug") -> dict[str, Any]:
        """Replace a tracked, generated, still-unmodified file (automatic correction path).
        User-modified or untracked files need the normal overwrite approval flow instead."""
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise CreatorWorkspaceError("file exceeds size limit")
        self._require(pid, actor, "correct_generated_file", None)
        with self._lock:
            target = self.resolve_path(pid, rel, actor)
            key = rel.replace("\\", "/")
            files = self.manifest(pid)
            meta = files.get(key)
            if meta is None or meta.get("origin") != "generated":
                raise ApprovalRequired("only tracked generated files can be corrected automatically")
            if not target.is_file() or _sha(target.read_bytes()) != meta["sha256"]:
                raise ApprovalRequired("file was modified outside Creator; overwrite requires approval")
            self._backup(pid, key, target)
            _atomic_write(target, data)
            files[key] = {**meta, "sha256": _sha(data), "size": len(data), "updated_at": _now(), "corrected": True}
            self._save_manifest(pid, files)
            self._history(pid, actor, "correct_file", key)
            return {"path": key, **files[key]}

    _ARTIFACT_KINDS = ("preview", "deliveries")
    _ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

    def _artifact_path(self, pid: str, kind: str, name: str) -> Path:
        if kind not in self._ARTIFACT_KINDS or not self._ARTIFACT_NAME.match(name or "") or ".." in name:
            raise CreatorWorkspaceError("invalid artifact kind or name")
        return self._pdir(pid) / CONTROL_DIR / kind / name

    def write_artifact(self, pid: str, kind: str, name: str, data: bytes, *, overwrite: bool = False,
                       actor: str = "creator") -> str:
        """Write a derived artifact (preview file / delivery zip) into the project's control area.
        Never touches project files; deliveries are never overwritten."""
        self._require(pid, actor, "write_generated_file", None)
        if len(data) > 50 * 1024 * 1024:
            raise CreatorWorkspaceError("artifact too large")
        with self._lock:
            path = self._artifact_path(pid, kind, name)
            if path.exists() and (not overwrite or kind == "deliveries"):
                raise CollisionError("artifact already exists")
            _atomic_write(path, data)
            self._history(pid, actor, f"write_{kind}", name)
            return f"{CONTROL_DIR}/{kind}/{name}"

    def read_artifact(self, pid: str, kind: str, name: str) -> bytes:
        path = self._artifact_path(pid, kind, name)
        if not path.is_file():
            raise CreatorWorkspaceError("artifact not found")
        return path.read_bytes()

    def list_artifacts(self, pid: str, kind: str) -> list[str]:
        if kind not in self._ARTIFACT_KINDS:
            raise CreatorWorkspaceError("invalid artifact kind")
        d = self._pdir(pid) / CONTROL_DIR / kind
        return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []

    def clear_artifacts(self, pid: str, kind: str, actor: str = "creator") -> int:
        """Remove derived PREVIEW files only (regenerable). Deliveries are never deleted."""
        if kind != "preview":
            raise ApprovalRequired("only preview artifacts can be cleared")
        n = 0
        with self._lock:
            for name in self.list_artifacts(pid, kind):
                self._artifact_path(pid, kind, name).unlink()
                n += 1
        return n

    _RECORD_KINDS = ("generations", "reports", "debug", "delivery", "memory")
    _RECORD_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

    def save_control_record(self, pid: str, kind: str, name: str, data: dict[str, Any]) -> None:
        if kind not in self._RECORD_KINDS or not self._RECORD_NAME.match(name or ""):
            raise CreatorWorkspaceError("invalid record kind or name")
        pdir = self._pdir(pid)
        _atomic_write(pdir / CONTROL_DIR / kind / f"{name}.json", json.dumps(data, indent=2, sort_keys=True).encode())

    def load_control_record(self, pid: str, kind: str, name: str) -> dict[str, Any]:
        if kind not in self._RECORD_KINDS or not self._RECORD_NAME.match(name or ""):
            raise CreatorWorkspaceError("invalid record kind or name")
        p = self._pdir(pid) / CONTROL_DIR / kind / f"{name}.json"
        if not p.is_file():
            raise CreatorWorkspaceError("record not found")
        return json.loads(p.read_text("utf-8"))

    def list_control_records(self, pid: str, kind: str) -> list[str]:
        if kind not in self._RECORD_KINDS:
            raise CreatorWorkspaceError("invalid record kind")
        d = self._pdir(pid) / CONTROL_DIR / kind
        return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []

    def _backup(self, pid: str, key: str, target: Path) -> None:
        dest = self.root / pid / CONTROL_DIR / "backups" / (_now().replace(":", "-") + "_" + uuid.uuid4().hex[:6]) / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)

    # ---------- integrity ----------
    def verify_integrity(self, pid: str) -> dict[str, list[str]]:
        pdir = self._pdir(pid)
        files = self.manifest(pid)
        modified, missing = [], []
        for key, meta in files.items():
            p = pdir / key
            if not p.is_file():
                missing.append(key)
            elif _sha(p.read_bytes()) != meta["sha256"]:
                modified.append(key)
        untracked = []
        for p in pdir.rglob("*"):
            if p.is_file() and not p.is_symlink():
                rel = p.relative_to(pdir).as_posix()
                if not rel.startswith(CONTROL_DIR + "/") and rel not in files:
                    untracked.append(rel)
        return {"modified": sorted(modified), "missing": sorted(missing), "untracked": sorted(untracked),
                "ok": not (modified or missing)}

    # ---------- checkpoints ----------
    def _ckpt_dir(self, pid: str) -> Path:
        return self.root / pid / CONTROL_DIR / "checkpoints"

    def list_checkpoints(self, pid: str) -> list[str]:
        self._pdir(pid)
        return sorted(p.name for p in self._ckpt_dir(pid).iterdir() if _CKPT.match(p.name))

    def create_checkpoint(self, pid: str, label: str = "", actor: str = "creator", *, skip_missing: bool = False) -> str:
        self._require(pid, actor, "write_generated_file", None)
        with self._lock:
            files = self.manifest(pid)
            cid = f"ckpt_{len(self.list_checkpoints(pid)) + 1:04d}"
            cdir = self._ckpt_dir(pid) / cid
            (cdir / "files").mkdir(parents=True)
            snap: dict[str, dict[str, Any]] = {}
            for key in files:
                src = self.resolve_path(pid, key, actor)
                if not src.is_file():
                    if skip_missing:
                        continue
                    raise CreatorWorkspaceError(f"tracked file missing, cannot checkpoint: {key}")
                dst = cdir / "files" / key
                dst.parent.mkdir(parents=True, exist_ok=True)
                blob = src.read_bytes()
                _atomic_write(dst, blob)
                # snapshot records the content actually captured (files may have drifted from the manifest)
                snap[key] = {**files[key], "sha256": _sha(blob), "size": len(blob)}
            _atomic_write(cdir / "checkpoint.json",
                          json.dumps({"id": cid, "label": label[:100], "created_at": _now(), "files": snap},
                                     indent=2, sort_keys=True).encode())
            self._history(pid, actor, "checkpoint", f"{cid} {label}")
            return cid

    def rollback(self, pid: str, cid: str, *, actor: str = "creator",
                 approval: Optional[ApprovalDecision] = None) -> dict[str, list[str]]:
        """Restore tracked files to a checkpoint. Untracked (user) files are never touched.
        Removing files created after the checkpoint needs delete_file approval."""
        if not isinstance(cid, str) or not _CKPT.match(cid):
            raise CreatorWorkspaceError("invalid checkpoint id")
        with self._lock:
            pdir = self._pdir(pid)
            cdir = self._ckpt_dir(pid) / cid
            if not (cdir / "checkpoint.json").is_file():
                raise CreatorWorkspaceError("unknown checkpoint")
            snap = json.loads((cdir / "checkpoint.json").read_text("utf-8"))["files"]
            current = self.manifest(pid)
            to_remove = sorted(set(current) - set(snap))
            if to_remove:
                self._require(pid, actor, "delete_file", approval)
            # preflight: restoring must not collide with untracked files
            for key in snap:
                if key not in current and self.resolve_path(pid, key, actor).exists():
                    raise CollisionError(f"untracked file blocks restore: {key}")
            for key, meta in snap.items():  # checkpoint payload integrity
                blob = cdir / "files" / key
                if not blob.is_file() or _sha(blob.read_bytes()) != meta["sha256"]:
                    raise CreatorWorkspaceError(f"checkpoint corrupted: {key}")
            safety = self.create_checkpoint(pid, f"pre-rollback to {cid}", actor, skip_missing=True)
            restored, removed = [], []
            for key, meta in snap.items():
                target = self.resolve_path(pid, key, actor)
                if target.is_file() and _sha(target.read_bytes()) == meta["sha256"]:
                    continue
                _atomic_write(target, (cdir / "files" / key).read_bytes())
                restored.append(key)
            for key in to_remove:
                t = self.resolve_path(pid, key, actor)
                if t.is_file():
                    t.unlink()
                removed.append(key)
            self._save_manifest(pid, dict(snap))
            self._history(pid, actor, "rollback", f"{cid} restored={len(restored)} removed={len(removed)} safety={safety}")
            return {"restored": sorted(restored), "removed": sorted(removed), "safety_checkpoint": [safety]}
