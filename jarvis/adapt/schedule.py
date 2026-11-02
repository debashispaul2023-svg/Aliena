"""Optional scheduler. External actions still need approval. No background daemon required."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScheduledTask:
    name: str
    cron: str
    action: str
    external: bool = False
    paused: bool = False
    history: list[str] = field(default_factory=list)

    def can_run(self, approved: bool) -> bool:
        if self.paused:
            return False
        if self.external and not approved:
            return False
        return True
