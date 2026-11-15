"""Feature 6 final verification. No generated-code execution."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from jarvis.resources.downloader import DownloadError, DownloadManager, validate_url
from jarvis.resources.safety import is_blocked_host, safe_extract_zip


def test_block_localhost_private_and_bad_scheme():
    for url in (
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://10.1.2.3/x",
        "http://169.254.169.254/x",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ):
        with pytest.raises(DownloadError):
            validate_url(url)
    assert is_blocked_host("::1") or is_blocked_host("127.0.0.1")


def test_zip_path_escape_rejected(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "nope")
        zf.writestr("/tmp/abs.txt", "nope")
    with pytest.raises(ValueError):
        safe_extract_zip(archive, tmp_path / "out")


def test_duplicate_not_overwritten(tmp_path: Path):
    root = tmp_path / "store"
    mgr = DownloadManager(root)
    dest = mgr._destination("keep.txt")
    dest.write_text("keep\n", encoding="utf-8")
    result = mgr.download("https://example.com/keep.txt", filename="keep.txt")
    assert result.success is False
    assert result.error_code == "exists"
    assert dest.read_text(encoding="utf-8") == "keep\n"


def test_live_w3c_dummy_pdf(tmp_path: Path):
    url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    expected = "3df79d34abbca99308e79cb94461c1893582604d68329a41fd4bec1885e6adb4"
    mgr = DownloadManager(tmp_path / "live")
    result = mgr.download(url, filename="dummy.pdf", expected_sha256=expected)
    if not result.success:
        pytest.skip(f"live download blocked: {result.error}")
    assert result.size == 13264
    assert result.sha256 == expected
    assert Path(result.path).is_file()
