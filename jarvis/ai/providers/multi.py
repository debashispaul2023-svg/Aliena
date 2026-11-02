"""Multi-source search: fan-out to several adapters and merge results."""

from __future__ import annotations

from typing import Any, Optional, Sequence


class MultiSearchAdapter:
    """Query multiple SearchAdapter instances and merge/deduplicate results.

    mode is LIVE if any sub-adapter contributed LIVE hits; otherwise the
    highest-priority non-empty adapter mode, or OFFLINE if empty.
    """

    def __init__(self, adapters: Sequence[Any]) -> None:
        self.adapters = list(adapters)
        self.last_errors: dict[str, str] = {}

    @property
    def mode(self) -> str:
        modes = [getattr(a, "mode", "OFFLINE") for a in self.adapters]
        if "LIVE" in modes:
            return "LIVE"
        if "MOCKED" in modes:
            return "MOCKED"
        return "OFFLINE"

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.last_errors = {}
        merged: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        per = max(1, limit)  # each provider can return up to limit; we trim later
        for adapter in self.adapters:
            name = type(adapter).__name__
            try:
                hits = adapter.search(query, limit=per) or []
            except Exception as exc:  # pragma: no cover - defensive
                self.last_errors[name] = str(exc)
                continue
            err = getattr(adapter, "last_error", None)
            if err:
                self.last_errors[name] = str(err)
            for h in hits:
                if not isinstance(h, dict):
                    continue
                url = str(h.get("url") or "").strip()
                title = str(h.get("title") or "").strip()
                if not url and not title:
                    continue
                key = url.lower() if url else title.lower()
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                # Ensure source attribution
                if not h.get("source"):
                    h = dict(h)
                    h["source"] = name
                merged.append(h)
                if len(merged) >= limit * 3:
                    break
        return merged[: limit * 3]  # finder will rank and trim
