"""Project memory separate from Aliena historical databases."""

from __future__ import annotations

import json
from pathlib import Path


class ProjectMemory:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def add(self, item: dict) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data.append(item)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def all(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8"))
