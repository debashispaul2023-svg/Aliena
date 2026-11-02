"""Resource Finder — discover and rank resources without inventing results.

OFFLINE mode ranks provided candidates deterministically.
LIVE mode may use an injected search adapter; never fabricates URLs.
Does not install packages or execute discovered code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol


@dataclass
class ResourceCandidate:
    title: str
    url: str
    description: str = ""
    source: str = ""  # e.g. pypi, docs, github, fixture
    kind: str = "unknown"  # package | docs | repo | api | tool | other
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceFindResult:
    query: str
    candidates: list[ResourceCandidate]
    mode: str  # MOCKED | OFFLINE | LIVE
    consulted: list[str] = field(default_factory=list)
    error: Optional[str] = None
    notes: str = ""


class SearchAdapter(Protocol):
    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return raw dicts with title/url/description/source. Must not invent."""
        ...


class FixtureSearchAdapter:
    """Explicit fixture adapter — results are MOCKED."""

    mode = "MOCKED"

    def __init__(self, fixtures: Optional[dict[str, list[dict[str, Any]]]] = None) -> None:
        self._fixtures = fixtures or {}

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        key = query.strip().lower()
        # exact then substring match on fixture keys
        if key in self._fixtures:
            return list(self._fixtures[key][:limit])
        for k, rows in self._fixtures.items():
            if k in key or key in k:
                return list(rows[:limit])
        return []


class NullSearchAdapter:
    """Reports no results; used when network is unavailable."""

    mode = "OFFLINE"

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return []


def _tokenize_score(item: dict[str, Any], query: str) -> tuple[float, list[str]]:
    """Explainable ranking: prefer official docs, exact token overlap, known kinds."""
    reasons: list[str] = []
    score = 0.0
    title = (item.get("title") or "").lower()
    url = (item.get("url") or "").lower()
    desc = (item.get("description") or "").lower()
    source = (item.get("source") or "").lower()
    kind = (item.get("kind") or "").lower()
    q_tokens = [t for t in re.split(r"\W+", query.lower()) if t]

    # Official / primary sources
    if any(x in url for x in ("docs.python.org", "readthedocs.io", "developer.mozilla.org", "docs.github.com")):
        score += 3.0
        reasons.append("official documentation host")
    if source in ("pypi", "docs", "official", "github"):
        score += 2.0
        reasons.append(f"source={source}")
    if kind == "docs":
        score += 1.5
        reasons.append("kind=docs")
    if kind == "package":
        score += 1.0
        reasons.append("kind=package")
    if kind == "repo":
        score += 0.8
        reasons.append("kind=repo")
    # stars hint when provided by GitHub
    stars = item.get("stars")
    if isinstance(stars, int) and stars > 0:
        score += min(2.0, stars / 5000.0)
        reasons.append(f"stars={stars}")

    # Token overlap
    blob = f"{title} {desc} {url}"
    hits = sum(1 for t in q_tokens if t in blob)
    if hits:
        score += float(hits)
        reasons.append(f"token_hits={hits}")

    # Prefer https
    if url.startswith("https://"):
        score += 0.5
        reasons.append("https")

    # Soft penalties
    if any(x in url for x in ("bit.ly", "tinyurl", "spam")):
        score -= 5.0
        reasons.append("suspicious shortener")

    return score, reasons


class ResourceFinder:
    """Locate and rank resources for a stated need.

    Never installs packages. Never executes discovered code.
    Does not invent search hits — empty adapter ⇒ empty results.
    """

    def __init__(self, adapter: Optional[SearchAdapter] = None) -> None:
        self.adapter = adapter or NullSearchAdapter()
        self._history: list[ResourceFindResult] = []

    def find(
        self,
        need: str,
        *,
        limit: int = 5,
        extra_candidates: Optional[list[dict[str, Any]]] = None,
    ) -> ResourceFindResult:
        query = (need or "").strip()
        if not query:
            return ResourceFindResult(
                query=query,
                candidates=[],
                mode=getattr(self.adapter, "mode", "OFFLINE"),
                error="Empty resource need",
            )

        consulted: list[str] = []
        raw: list[dict[str, Any]] = []
        mode = getattr(self.adapter, "mode", "OFFLINE")
        err: Optional[str] = None

        try:
            hits = self.adapter.search(query, limit=limit * 2)
            if hits:
                consulted.append(type(self.adapter).__name__)
            raw.extend(hits or [])
        except Exception as exc:
            err = f"Search adapter error: {exc}"

        if extra_candidates:
            raw.extend(extra_candidates)
            consulted.append("extra_candidates")

        ranked: list[ResourceCandidate] = []
        for item in raw:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title and not url:
                continue  # skip malformed
            score, reasons = _tokenize_score(item, query)
            meta = {
                k: v
                for k, v in item.items()
                if k not in ("title", "url", "description", "source", "kind") and v is not None
            }
            ranked.append(
                ResourceCandidate(
                    title=title or url,
                    url=url,
                    description=str(item.get("description") or ""),
                    source=str(item.get("source") or ""),
                    kind=str(item.get("kind") or "unknown"),
                    score=score,
                    reasons=reasons,
                    metadata=meta,
                )
            )
        ranked.sort(key=lambda c: (-c.score, c.title))
        ranked = ranked[:limit]

        result = ResourceFindResult(
            query=query,
            candidates=ranked,
            mode=mode,
            consulted=consulted,
            error=err,
            notes="Ranking is deterministic. No packages were installed.",
        )
        self._history.append(result)
        return result

    def history(self) -> list[ResourceFindResult]:
        return list(self._history)

# Re-export live adapter for convenience
try:
    from jarvis.ai.providers.web_search import DuckDuckGoHTMLAdapter  # noqa: F401
except Exception:  # pragma: no cover
    DuckDuckGoHTMLAdapter = None  # type: ignore
