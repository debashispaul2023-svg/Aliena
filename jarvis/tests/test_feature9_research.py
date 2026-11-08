"""Feature 9 focused tests. No live research fetch."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.research.engine import ResearchEngine
from jarvis.research.storage import ResearchStore


def test_https_and_ssrf_blocked(tmp_path: Path):
    store = ResearchStore(tmp_path / "research.db")
    engine = ResearchEngine(store)
    with pytest.raises(ValueError):
        engine.add_source_backed_note("x", "y", "http://example.com/a")
    with pytest.raises(ValueError):
        engine.add_source_backed_note("x", "y", "https://127.0.0.1/a")
    store.close()


def test_duplicate_and_search(tmp_path: Path):
    store = ResearchStore(tmp_path / "research.db")
    engine = ResearchEngine(store)
    first = engine.add_source_backed_note("Aliena docs", "modular base", "https://example.com/docs", category="docs")
    second = engine.add_source_backed_note("Aliena docs", "modular base", "https://example.com/docs", category="docs")
    assert first == second
    hits = engine.search("modular", category="docs")
    assert hits
    store.close()


def test_summary_does_not_claim_verified(tmp_path: Path):
    store = ResearchStore(tmp_path / "research.db")
    engine = ResearchEngine(store)
    summary = engine.summarize("fact one\nfact two", "https://example.com/source")
    assert summary["verified"] is False
    assert "https://example.com/source" == summary["source"]
    store.close()
