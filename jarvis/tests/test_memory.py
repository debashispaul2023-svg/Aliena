"""Tests for permanent SQLite memory (Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.memory.store import (
    MemoryStore,
    CATEGORY_LONG_TERM,
    CATEGORY_USER_PROFILE,
    CATEGORY_PREFERENCE,
    CATEGORY_PROJECT,
    CATEGORY_CONVERSATION,
    looks_like_secret,
)


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    db = tmp_path / "test_memory.db"
    s = MemoryStore(db)
    yield s
    s.close()


def test_save_and_get(store: MemoryStore) -> None:
    rec = store.save("User likes black coffee", category=CATEGORY_PREFERENCE, tags=["drink"])
    assert rec is not None
    assert rec.id
    loaded = store.get(rec.id)
    assert loaded is not None
    assert loaded.content == "User likes black coffee"
    assert loaded.category == CATEGORY_PREFERENCE
    assert "drink" in loaded.tags


def test_duplicate_prevention(store: MemoryStore) -> None:
    a = store.save("I live in Siliguri", category=CATEGORY_LONG_TERM)
    b = store.save("I live in Siliguri", category=CATEGORY_LONG_TERM)
    assert a is not None and b is not None
    assert a.id == b.id
    assert store.count(CATEGORY_LONG_TERM) == 1


def test_secret_rejection(store: MemoryStore) -> None:
    assert looks_like_secret("my api key is sk-abcdefghijklmnopqrstuvwxyz1234")
    assert looks_like_secret("password: hunter2")
    rec = store.save("GEMINI_API_KEY is AIzaSyDummyKey123456789012345", category=CATEGORY_LONG_TERM)
    assert rec is None
    assert store.count() == 0


def test_update_and_delete(store: MemoryStore) -> None:
    rec = store.save("Original fact", category=CATEGORY_LONG_TERM)
    assert rec is not None
    updated = store.update(rec.id, content="Updated fact", importance=0.9)
    assert updated is not None
    assert updated.content == "Updated fact"
    assert store.delete(rec.id) is True
    assert store.get(rec.id) is None


def test_search_and_category_filter(store: MemoryStore) -> None:
    store.save("Working on Jarvis AI assistant", category=CATEGORY_PROJECT, tags=["jarvis"])
    store.save("Prefers Banglish replies", category=CATEGORY_PREFERENCE)
    store.save("Goal: ship daily automation", category=CATEGORY_LONG_TERM, tags=["goal"])
    hits = store.search("Jarvis", limit=5)
    assert any("Jarvis" in h.content for h in hits)
    projects = store.list_by_category(CATEGORY_PROJECT)
    assert len(projects) == 1


def test_relevant_for_prompt_budget(store: MemoryStore) -> None:
    for i in range(20):
        store.save(f"Fact number {i} about the user hobbies and routines", category=CATEGORY_LONG_TERM)
    store.save("User name is Debashis", category=CATEGORY_USER_PROFILE, importance=0.95)
    results = store.relevant_for_prompt("what are my hobbies", limit=5, max_chars=400)
    assert len(results) <= 5
    total = sum(len(r.content) for r in results)
    assert total <= 400 or len(results) == 1


def test_persistence_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    s1 = MemoryStore(db)
    rec = s1.save("Persistent fact", category=CATEGORY_LONG_TERM)
    assert rec is not None
    rid = rec.id
    s1.close()

    s2 = MemoryStore(db)
    loaded = s2.get(rid)
    assert loaded is not None
    assert loaded.content == "Persistent fact"
    s2.close()


def test_migrate_from_json_once(tmp_path: Path) -> None:
    json_path = tmp_path / "jarvis_memory.json"
    data = [
        {"role": "user", "text": "hello there", "time": "2026-01-01T00:00:00"},
        {"role": "jarvis", "text": "hi!", "time": "2026-01-01T00:00:01"},
        {"role": "user", "text": "my api key is sk-abcdefghijklmnopqrst", "time": "2026-01-01T00:00:02"},
    ]
    json_path.write_text(json.dumps(data), encoding="utf-8")
    backup_dir = tmp_path / "backup"

    store = MemoryStore(tmp_path / "mig.db")
    n1 = store.migrate_from_json(json_path, backup_dir=backup_dir)
    assert n1 == 2  # secret line skipped
    assert store.count(CATEGORY_CONVERSATION) == 2
    # Second call must be a no-op
    n2 = store.migrate_from_json(json_path, backup_dir=backup_dir)
    assert n2 == 0
    assert store.count(CATEGORY_CONVERSATION) == 2
    # Original file still exists
    assert json_path.exists()
    # Backup was created
    backups = list(backup_dir.glob("jarvis_memory.json.migrated_*"))
    assert len(backups) >= 1
    store.close()


def test_format_for_prompt(store: MemoryStore) -> None:
    rec = store.save("Likes dark mode", category=CATEGORY_PREFERENCE, tags=["ui"])
    assert rec is not None
    text = store.format_for_prompt([rec])
    assert "preference" in text
    assert "Likes dark mode" in text
