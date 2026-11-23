"""Controlled project writer. No shell, no eval, no Phase 6F execution."""

from __future__ import annotations

from pathlib import Path


class WorkspaceWriter:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, relative: str, content: str) -> Path:
        target = (self.root / relative).resolve()
        if self.root not in target.parents and target != self.root:
            raise ValueError("path traversal")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target
