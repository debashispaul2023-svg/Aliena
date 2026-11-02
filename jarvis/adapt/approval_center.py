"""Approval queue for external actions. Fail closed."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ApprovalCenter:
    pending: dict[str, str] = field(default_factory=dict)
    decided: dict[str, bool] = field(default_factory=dict)

    def request(self, action: str, target: str) -> str:
        key = f"{action}:{target}"
        self.pending[key] = action
        return key

    def decide(self, key: str, approved: bool) -> bool:
        self.pending.pop(key, None)
        self.decided[key] = approved
        return approved

    def is_allowed(self, key: str) -> bool:
        return self.decided.get(key, False)
