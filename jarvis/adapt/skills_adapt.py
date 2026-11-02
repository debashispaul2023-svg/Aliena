"""Skill drafts that register only after approval.

Uses the existing skill registry when available. Does not create a second store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SkillDraft:
    name: str
    body: str
    version: str = "0.1.0"
    score: float = 0.0
    approved: bool = False
    tested: bool = False
    tags: list[str] = field(default_factory=list)
    previous: Optional["SkillDraft"] = None

    def validate(self) -> list[str]:
        errors = []
        if not self.name.strip():
            errors.append("name required")
        if not self.body.strip():
            errors.append("body required")
        if self.score < 0 or self.score > 1:
            errors.append("score out of range")
        return errors

    def activate(self) -> bool:
        if self.validate():
            return False
        if not self.tested or not self.approved:
            return False
        return True

    def rollback(self) -> Optional["SkillDraft"]:
        return self.previous


def from_experience(name: str, success: str) -> SkillDraft:
    return SkillDraft(name=name, body=success, score=0.5)


def is_duplicate(name: str, existing: list[str]) -> bool:
    return name.strip().lower() in {e.strip().lower() for e in existing}


def suggest_improvement(name: str, failure: str) -> str:
    return f"Review skill {name} after failure: {failure}. Do not auto-activate."
