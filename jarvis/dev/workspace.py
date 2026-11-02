"""Path-confined development workspace (Phase 6B).

Application-level path boundary only — NOT an OS-level security sandbox.
All file operations are restricted to an authorized base root and project
subdirectory. Does not execute files written into the workspace.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Optional, Union

StrPath = Union[str, Path]

# Project / file name rules
_SAFE_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_UNSAFE_FILE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


class WorkspaceError(Exception):
    """Path or workspace safety violation."""

    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def validate_project_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise WorkspaceError("Project name is required", code="bad_name")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise WorkspaceError("Unsafe project name", code="bad_name")
    if not _SAFE_PROJECT.match(name):
        raise WorkspaceError(
            "Project name must be alphanumeric/._- and start with alphanumeric",
            code="bad_name",
        )
    return name


def safe_rel_filename(name: str) -> str:
    """Sanitize a single path segment (basename)."""
    base = os.path.basename(str(name).replace("\\", "/")).strip().strip(".")
    if not base or base in {".", ".."}:
        raise WorkspaceError("Unsafe filename", code="bad_name")
    if ".." in base:
        raise WorkspaceError("Unsafe filename", code="bad_name")
    base = _UNSAFE_FILE_CHARS.sub("_", base)
    if not base:
        raise WorkspaceError("Unsafe filename", code="bad_name")
    return base[:200]


class DevWorkspace:
    """A single project directory under an authorized base root."""

    def __init__(self, root: Path, project_name: str) -> None:
        self.root = root.resolve()
        self.project_name = validate_project_name(project_name)
        self.project_root = (self.root / self.project_name).resolve()
        try:
            self.project_root.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError(
                "Project path escapes workspace root", code="path_escape"
            ) from exc
        self.project_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def resolve(self, relative: StrPath) -> Path:
        """Resolve a relative path and ensure it stays under project_root."""
        rel = str(relative).replace("\\", "/").lstrip("/")
        if not rel or rel == ".":
            return self.project_root
        # Disallow absolute inputs
        if Path(relative).is_absolute() or str(relative).startswith("/"):
            raise WorkspaceError(
                "Absolute paths are not allowed", code="absolute_path"
            )
        parts = Path(rel).parts
        if any(p == ".." for p in parts):
            raise WorkspaceError("Path traversal rejected", code="traversal")
        if any(p == "" for p in parts):
            raise WorkspaceError("Invalid path", code="bad_name")
        candidate = (self.project_root / rel).resolve()
        try:
            candidate.relative_to(self.project_root.resolve())
        except ValueError as exc:
            raise WorkspaceError(
                f"Path escapes project workspace: {candidate}", code="path_escape"
            ) from exc
        # Symlink escape: if any parent is a symlink pointing outside, reject
        self._assert_no_symlink_escape(candidate)
        return candidate

    def _assert_no_symlink_escape(self, candidate: Path) -> None:
        """Reject if candidate or ancestors escape via symlink."""
        root = self.project_root.resolve()
        # Walk from root toward candidate; each component must stay under root
        try:
            rel = candidate.relative_to(root)
        except ValueError as exc:
            raise WorkspaceError("Symlink or path escape detected", code="symlink_escape") from exc
        cur = root
        for part in rel.parts:
            cur = cur / part
            if cur.is_symlink():
                real = cur.resolve()
                try:
                    real.relative_to(root)
                except ValueError as exc:
                    raise WorkspaceError(
                        "Symlink escapes project workspace", code="symlink_escape"
                    ) from exc

    def contains(self, path: StrPath) -> bool:
        try:
            p = Path(path).resolve()
            p.relative_to(self.project_root.resolve())
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def list_files(self, subdir: str = "", *, recursive: bool = True) -> list[str]:
        base = self.resolve(subdir) if subdir else self.project_root
        if not base.exists():
            return []
        if not base.is_dir():
            raise WorkspaceError("Not a directory", code="not_dir")
        out: list[str] = []
        if recursive:
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    out.append(str(p.relative_to(self.project_root)).replace("\\", "/"))
        else:
            for p in sorted(base.iterdir()):
                if p.is_file():
                    out.append(str(p.relative_to(self.project_root)).replace("\\", "/"))
        return out

    def read_text(self, relative: StrPath, *, encoding: str = "utf-8") -> str:
        path = self.resolve(relative)
        if not path.is_file():
            raise WorkspaceError(f"File not found: {relative}", code="not_found")
        return path.read_text(encoding=encoding)

    def read_bytes(self, relative: StrPath) -> bytes:
        path = self.resolve(relative)
        if not path.is_file():
            raise WorkspaceError(f"File not found: {relative}", code="not_found")
        return path.read_bytes()

    def write_text(
        self,
        relative: StrPath,
        content: str,
        *,
        encoding: str = "utf-8",
        overwrite: bool = False,
        make_parents: bool = True,
    ) -> Path:
        path = self.resolve(relative)
        if path.exists() and not overwrite:
            raise WorkspaceError(
                f"File exists (overwrite=False): {relative}", code="exists"
            )
        if make_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Re-validate after mkdir (parents must remain inside root)
            path = self.resolve(relative)

        # Atomic write: temp in same directory then replace
        tmp_path: Optional[Path] = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".jarvis_ws_",
                suffix=".tmp",
                dir=str(path.parent),
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding=encoding) as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            if path.exists() and overwrite:
                path.unlink()
            os.replace(str(tmp_path), str(path))
            tmp_path = None
            return path
        except Exception:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    def write_bytes(
        self,
        relative: StrPath,
        content: bytes,
        *,
        overwrite: bool = False,
        make_parents: bool = True,
    ) -> Path:
        path = self.resolve(relative)
        if path.exists() and not overwrite:
            raise WorkspaceError(
                f"File exists (overwrite=False): {relative}", code="exists"
            )
        if make_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
            path = self.resolve(relative)
        tmp_path: Optional[Path] = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".jarvis_ws_",
                suffix=".tmp",
                dir=str(path.parent),
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            if path.exists() and overwrite:
                path.unlink()
            os.replace(str(tmp_path), str(path))
            tmp_path = None
            return path
        except Exception:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    def mkdir(self, relative: StrPath) -> Path:
        path = self.resolve(relative)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def exists(self, relative: StrPath) -> bool:
        try:
            return self.resolve(relative).exists()
        except WorkspaceError:
            return False


class WorkspaceManager:
    """Manages multiple project workspaces under one authorized base root.

    This enforces application-level path boundaries only. It is not an
    OS-level sandbox (no seccomp, container, or privilege drop).
    """

    def __init__(self, base_root: StrPath) -> None:
        self.base_root = Path(base_root).resolve()
        self.base_root.mkdir(parents=True, exist_ok=True)

    def create_project(self, name: str) -> DevWorkspace:
        name = validate_project_name(name)
        return DevWorkspace(self.base_root, name)

    def open_project(self, name: str) -> DevWorkspace:
        name = validate_project_name(name)
        path = (self.base_root / name).resolve()
        try:
            path.relative_to(self.base_root)
        except ValueError as exc:
            raise WorkspaceError("Project escapes base root", code="path_escape") from exc
        if not path.exists():
            raise WorkspaceError(f"Project not found: {name}", code="not_found")
        if not path.is_dir():
            raise WorkspaceError(f"Not a directory: {name}", code="not_dir")
        return DevWorkspace(self.base_root, name)

    def list_projects(self) -> list[str]:
        if not self.base_root.exists():
            return []
        return sorted(
            p.name
            for p in self.base_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def is_under_base(self, path: StrPath) -> bool:
        try:
            Path(path).resolve().relative_to(self.base_root)
            return True
        except Exception:
            return False
