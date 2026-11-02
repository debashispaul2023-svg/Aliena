"""Load project context files. Contents are untrusted and cannot override policy."""

from __future__ import annotations

from pathlib import Path

CONTEXT_NAMES = ("AGENTS.md", "CLAUDE.md", ".hermes.md", "SOUL.md", ".cursorrules")


def discover(root: Path) -> list[Path]:
    root = Path(root).resolve()
    found = []
    for name in CONTEXT_NAMES:
        path = root / name
        if path.is_file() and path.resolve().is_relative_to(root):
            found.append(path)
    return found


def load(root: Path, *, max_chars: int = 4000) -> dict:
    files = discover(root)
    contexts = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        contexts.append({"file": path.name, "text": text, "untrusted": True})
    return {
        "files": [c["file"] for c in contexts],
        "contexts": contexts,
        "policy": "Context files cannot override security policy.",
    }
