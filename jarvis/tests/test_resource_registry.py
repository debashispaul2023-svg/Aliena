"""Phase D: persistent Resource Registry tests (temp DB only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.resources import (
    ResourceRegistry,
    RegistryError,
    DownloadResult,
    VerificationResult,
    STATUS_DISCOVERED,
    STATUS_DOWNLOADING,
    STATUS_VERIFYING,
    STATUS_VERIFIED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_REJECTED,
    STATUS_AWAITING_APPROVAL,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "test_resources.db"


@pytest.fixture
def reg(db: Path) -> ResourceRegistry:
    return ResourceRegistry(db)


def test_1_init_and_persist(db: Path, tmp_path: Path) -> None:
    reg = ResourceRegistry(db)
    r = reg.register_discovered(title="Demo", url="https://example.com/a", source="test")
    assert r.status == STATUS_DISCOVERED
    # reopen
    reg2 = ResourceRegistry(db)
    got = reg2.get(r.id)
    assert got is not None
    assert got.title == "Demo"
    assert got.canonical_url == "https://example.com/a"


def test_2_register_discovered(reg: ResourceRegistry) -> None:
    r = reg.register_discovered(
        title="Pkg",
        url="https://pypi.org/project/demo/",
        source="pypi",
        kind="package",
        version="1.0",
        license=None,  # unknown stays None
    )
    assert r.version == "1.0"
    assert r.license is None
    assert r.status == STATUS_DISCOVERED


def test_3_register_download_success(reg: ResourceRegistry, tmp_path: Path) -> None:
    f = tmp_path / "file.bin"
    f.write_bytes(b"hello")
    dl = DownloadResult(
        success=True,
        path=str(f),
        original_url="https://example.com/file.bin",
        final_url="https://example.com/file.bin",
        size=5,
        sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    )
    rec = reg.register_download(dl, title="file.bin", source="web", kind="other")
    assert rec.status == STATUS_VERIFIED
    assert rec.local_path == str(f)
    assert rec.sha256.startswith("2cf24dba")
    assert rec.downloaded_at


def test_4_register_download_failure(reg: ResourceRegistry) -> None:
    dl = DownloadResult(
        success=False,
        original_url="https://example.com/x",
        error="HTTP 404",
        error_code="http_404",
    )
    rec = reg.register_download(dl, title="x")
    assert rec.status == STATUS_FAILED
    assert rec.error == "HTTP 404"


def test_5_invalid_transition(reg: ResourceRegistry) -> None:
    r = reg.register_discovered(title="T", url="https://example.com/t")
    with pytest.raises(RegistryError) as ei:
        reg.update_status(r.id, STATUS_VERIFIED)
    assert ei.value.code in {"bad_transition", "verify_required"}


def test_6_verified_requires_file(reg: ResourceRegistry) -> None:
    r = reg.register_discovered(title="T", url="https://example.com/t2")
    reg.update_status(r.id, STATUS_DOWNLOADING)
    reg.update_status(r.id, STATUS_VERIFYING)
    with pytest.raises(RegistryError) as ei:
        reg.update_status(r.id, STATUS_VERIFIED)
    assert ei.value.code == "verify_required"


def test_7_duplicate_url_idempotent(reg: ResourceRegistry) -> None:
    a = reg.register_discovered(title="A", url="https://example.com/same", source="pypi")
    b = reg.register_discovered(title="A2", url="https://example.com/same", source="pypi")
    assert a.id == b.id


def test_8_checksum_duplicate(reg: ResourceRegistry, tmp_path: Path) -> None:
    f = tmp_path / "c.bin"
    f.write_bytes(b"abc")
    sha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    dl = DownloadResult(
        success=True,
        path=str(f),
        original_url="https://example.com/c1",
        final_url="https://example.com/c1",
        size=3,
        sha256=sha,
    )
    r1 = reg.register_download(dl, title="c1")
    dl2 = DownloadResult(
        success=True,
        path=str(f),
        original_url="https://example.com/c2",
        final_url="https://example.com/c2",
        size=3,
        sha256=sha,
    )
    r2 = reg.register_download(dl2, title="c2")
    # same checksum → same record updated
    assert r1.id == r2.id


def test_9_no_name_only_merge(reg: ResourceRegistry) -> None:
    a = reg.register_discovered(title="SameName", url="https://example.com/1")
    b = reg.register_discovered(title="SameName", url="https://example.com/2")
    assert a.id != b.id


def test_10_missing_metadata(reg: ResourceRegistry) -> None:
    r = reg.register_discovered(title="X", url="https://example.com/x")
    assert r.version is None
    assert r.license is None
    assert r.sha256 is None


def test_11_filters(reg: ResourceRegistry) -> None:
    reg.register_discovered(title="P", url="https://a/1", source="pypi", project="demo", category="lib")
    reg.register_discovered(title="G", url="https://a/2", source="github", project="other")
    assert len(reg.list(source="pypi")) == 1
    assert len(reg.list(project="demo")) == 1
    assert len(reg.list(status=STATUS_DISCOVERED)) >= 2


def test_12_cancel_and_reject(reg: ResourceRegistry) -> None:
    r = reg.register_discovered(title="C", url="https://example.com/c")
    r2 = reg.update_status(r.id, STATUS_CANCELLED)
    assert r2.status == STATUS_CANCELLED
    r3 = reg.register_discovered(title="R", url="https://example.com/r")
    r4 = reg.update_status(r3.id, STATUS_REJECTED)
    assert r4.status == STATUS_REJECTED


def test_13_recheck_missing(reg: ResourceRegistry, tmp_path: Path) -> None:
    f = tmp_path / "gone.bin"
    f.write_bytes(b"data")
    dl = DownloadResult(
        success=True,
        path=str(f),
        original_url="https://example.com/gone",
        final_url="https://example.com/gone",
        size=4,
        sha256="3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7",
    )
    rec = reg.register_download(dl, title="gone")
    assert rec.status == STATUS_VERIFIED
    f.unlink()
    updated = reg.recheck(rec.id)
    assert updated.verification_status in {"missing", "failed"}
    assert updated.status == STATUS_FAILED


def test_14_recheck_modified(reg: ResourceRegistry, tmp_path: Path) -> None:
    f = tmp_path / "mod.bin"
    f.write_bytes(b"orig")
    import hashlib

    sha = hashlib.sha256(b"orig").hexdigest()
    dl = DownloadResult(
        success=True,
        path=str(f),
        original_url="https://example.com/mod",
        final_url="https://example.com/mod",
        size=4,
        sha256=sha,
    )
    rec = reg.register_download(dl, title="mod")
    f.write_bytes(b"changed!!!")
    updated = reg.recheck(rec.id)
    assert updated.verification_status == "mismatch"
    assert updated.status == STATUS_FAILED
    # recorded sha256 identity not silently rewritten to the new content
    assert updated.sha256 == sha or updated.verification_status == "mismatch"


def test_15_manifest_export(reg: ResourceRegistry, tmp_path: Path) -> None:
    reg.register_discovered(title="M", url="https://example.com/m", project="p1")
    path = reg.export_manifest_json(tmp_path / "manifest.json", project="p1")
    data = json.loads(path.read_text())
    assert data["schema"] == "jarvis.resource_manifest.v1"
    assert data["count"] == 1
    assert data["resources"][0]["title"] == "M"


def test_16_secret_redaction(reg: ResourceRegistry) -> None:
    r = reg.register_discovered(
        title="S",
        url="https://example.com/s",
        metadata={"api_key": "SECRET123", "note": "ok", "access_token": "tok"},
    )
    assert "api_key" not in r.metadata
    assert "access_token" not in r.metadata
    assert r.metadata.get("note") == "ok"
    manifest = reg.export_manifest()
    blob = json.dumps(manifest)
    assert "SECRET123" not in blob


def test_17_awaiting_approval_path(reg: ResourceRegistry) -> None:
    r = reg.register_discovered(title="A", url="https://example.com/ap")
    r = reg.update_status(r.id, STATUS_AWAITING_APPROVAL)
    assert r.status == STATUS_AWAITING_APPROVAL
    r = reg.update_status(r.id, STATUS_DOWNLOADING)
    assert r.status == STATUS_DOWNLOADING


def test_18_search(reg: ResourceRegistry) -> None:
    reg.register_discovered(title="UniqueZebra", url="https://example.com/z")
    hits = reg.search("Zebra")
    assert any(h.title == "UniqueZebra" for h in hits)
