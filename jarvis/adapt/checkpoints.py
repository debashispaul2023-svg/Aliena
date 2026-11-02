"""File checkpoints. Not a replacement for Git."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


class CheckpointError(RuntimeError):
    """Checkpoint failure."""


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create(root: Path, files: Iterable[str], *, task_id: str, store: Path) -> dict:
    root = Path(root).resolve()
    store = Path(store)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = store / f"{task_id}-{stamp}"
    dest.mkdir(parents=True, exist_ok=False)
    manifest = []
    for rel in files:
        if ".." in rel.split("/") or rel.startswith("/"):
            raise CheckpointError(f"unsafe path: {rel}")
        src = (root / rel).resolve()
        if not src.is_relative_to(root) or not src.is_file():
            raise CheckpointError(f"missing or outside root: {rel}")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        manifest.append({"path": rel, "sha256": _hash(src)})
    (dest / "manifest.json").write_text(json.dumps({"task_id": task_id, "files": manifest}, indent=2))
    return {"id": dest.name, "files": manifest}


def restore(root: Path, checkpoint: Path, *, preview: bool = False) -> dict:
    root = Path(root).resolve()
    checkpoint = Path(checkpoint)
    manifest = json.loads((checkpoint / "manifest.json").read_text())
    restored = []
    for item in manifest["files"]:
        rel = item["path"]
        src = checkpoint / rel
        dest = (root / rel).resolve()
        if not dest.is_relative_to(root):
            raise CheckpointError(f"restore escape: {rel}")
        if preview:
            restored.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        restored.append(rel)
    return {"restored": restored, "preview": preview}
