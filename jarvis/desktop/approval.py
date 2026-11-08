"""Explicit user approval for consequential desktop actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


@dataclass
class ApprovalRecord:
    approval_id: str
    action: str
    approved: bool
    reviewer: str
    created_at: str


@dataclass
class ApprovalManager:
    records: list[ApprovalRecord] = field(default_factory=list)

    def request(self, action: str, *, reviewer: str = "user", approved: bool = False) -> ApprovalRecord:
        rec = ApprovalRecord(
            approval_id=str(uuid.uuid4()),
            action=action,
            approved=approved,
            reviewer=reviewer,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.records.append(rec)
        return rec

    def is_approved(self, action: str) -> bool:
        for rec in reversed(self.records):
            if rec.action == action and rec.approved:
                return True
        return False
