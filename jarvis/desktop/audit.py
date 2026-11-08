"""Desktop automation audit log. Never stores credentials or secret contents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuditLogger:
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, action: str, status: str, *, detail: str = "") -> None:
        self.events.append(
            {
                "action": action,
                "status": status,
                "detail": detail[:200],
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    def list_events(self) -> list[dict[str, Any]]:
        return list(self.events)
