"""Lifecycle tests for persistent memory. Uses an isolated DB."""

from __future__ import annotations

from jarvis.memory.store import MemoryStore, CATEGORY_LONG_TERM, CATEGORY_ARCHIVE


def test_archive_backup_restore(tmp_path):
    db = tmp_path / "mem.db"
    store = MemoryStore(db)
    rec = store.save("User lives in Siliguri", category=CATEGORY_LONG_TERM)
    assert rec is not None
    archived = store.archive(rec.id)
    assert archived is not None
    assert archived.category == CATEGORY_ARCHIVE
    backup = store.backup(tmp_path / "mem.bak")
    store.delete(rec.id)
    assert store.count() == 0
    restored = store.restore(backup)
    assert restored == 1
    assert store.integrity_check() is True
    store.close()


def test_untrusted_source_capped(tmp_path):
    store = MemoryStore(tmp_path / "mem.db")
    rec = store.save("page said this", source="mcp", confidence=0.9)
    assert rec is not None
    assert rec.confidence <= 0.4
    store.close()


def test_contradiction(tmp_path):
    store = MemoryStore(tmp_path / "mem.db")
    store.save("User likes tea", category=CATEGORY_LONG_TERM)
    store.save("User does not like tea", category=CATEGORY_LONG_TERM)
    hits = store.find_contradictions()
    assert hits
    store.close()
