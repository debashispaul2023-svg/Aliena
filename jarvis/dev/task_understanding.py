"""Natural-language task understanding. Uses safe defaults."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskSpec:
    title: str
    kind: str
    needs_frontend: bool = False
    needs_backend: bool = False
    needs_database: bool = False
    features: list[str] = field(default_factory=list)


class TaskUnderstanding:
    def parse(self, text: str) -> TaskSpec:
        lower = text.lower()
        features = []
        if "menu" in lower:
            features.append("menu")
        if "contact" in lower:
            features.append("contact")
        if "admin" in lower:
            features.append("admin")
        if "auth" in lower or "login" in lower:
            features.append("auth")
        kind = "website" if "website" in lower or "restaurant" in lower else "app"
        return TaskSpec(
            title=text.strip()[:120],
            kind=kind,
            needs_frontend=True,
            needs_backend="backend" in lower or "api" in lower or "restaurant" in lower,
            needs_database="database" in lower or "menu" in lower,
            features=features,
        )
