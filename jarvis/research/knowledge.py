"""Research notes. Does not invent sources or fetch private networks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ResearchNote:
    title: str
    source_url: str
    summary: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class KnowledgeBase:
    def __init__(self) -> None:
        self.notes: list[ResearchNote] = []

    def add(self, title: str, source_url: str, summary: str) -> ResearchNote:
        if not source_url.startswith("https://"):
            raise ValueError("source must be https")
        note = ResearchNote(title=title, source_url=source_url, summary=summary)
        self.notes.append(note)
        return note

    def search(self, query: str) -> list[ResearchNote]:
        q = query.lower()
        return [n for n in self.notes if q in n.title.lower() or q in n.summary.lower()]
