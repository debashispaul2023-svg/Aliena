"""Research engine. Does not invent citations or fetch private networks."""

from __future__ import annotations

from datetime import datetime, timezone

from jarvis.research.security import validate_research_url
from jarvis.research.storage import ResearchStore


class ResearchEngine:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_source_backed_note(self, title: str, content: str, source_url: str, *, category: str = "", tags: str = "") -> int:
        url = validate_research_url(source_url)
        existing = self.store.find_duplicate(title, url)
        if existing is not None:
            return existing
        item_id = self.store.add_knowledge(title, content, url, category=category, tags=tags, created_at=self._now())
        self.store.add_history("add", title, self._now())
        return item_id

    def search(self, query: str, *, category: str = "") -> list[dict]:
        return self.store.search(query, category=category)

    def add_note(self, project: str, title: str, body: str, source_url: str) -> int:
        url = validate_research_url(source_url) if source_url else ""
        return self.store.add_note(project, title, body, url, self._now())

    def summarize(self, content: str, source_url: str) -> dict:
        url = validate_research_url(source_url)
        facts = [line.strip() for line in content.splitlines() if line.strip()][:5]
        return {
            "source": url,
            "supported": facts,
            "inference": [],
            "verified": False,
            "note": "source-backed only; not live-verified",
        }
