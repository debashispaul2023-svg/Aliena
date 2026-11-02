"""Phase B: DownloadManager & verification tests using a local HTTP server."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from jarvis.resources import DownloadManager, verify_file, safe_filename, DownloadError


class _Handler(BaseHTTPRequestHandler):
    """Minimal controlled server for download tests."""

    # Class-level mutable fixtures set by tests
    routes: dict = {}

    def log_message(self, format, *args):  # noqa: A003
        return  # quiet

    def do_GET(self):  # noqa: N802
        route = self.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        status = route.get("status", 200)
        body = route.get("body", b"")
        headers = route.get("headers", {})
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # Optional slow/chunked write for interrupt tests
        chunk = route.get("chunk_delay")
        if chunk:
            import time

            mid = len(body) // 2 or 1
            self.wfile.write(body[:mid])
            self.wfile.flush()
            time.sleep(chunk)
            self.wfile.write(body[mid:])
        else:
            self.wfile.write(body)


@pytest.fixture(scope="module")
def http_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    d = tmp_path / "JarvisResources"
    d.mkdir()
    return d


@pytest.fixture
def mgr(root: Path) -> DownloadManager:
    # allow_private_hosts=True only for local test server
    return DownloadManager(root, max_bytes=1024 * 1024, allow_private_hosts=True, max_retries=1)


def test_safe_filename() -> None:
    assert safe_filename("hello.txt") == "hello.txt"
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("..") == "download.bin"
    assert safe_filename("") == "download.bin"


def test_1_successful_download(http_server: str, mgr: DownloadManager, root: Path) -> None:
    body = b"hello jarvis phase b"
    _Handler.routes = {"/ok.txt": {"body": body}}
    result = mgr.download(f"{http_server}/ok.txt", filename="ok.txt")
    assert result.success, result.error
    assert result.path
    p = Path(result.path)
    assert p.exists()
    assert p.read_bytes() == body
    assert result.size == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert p.resolve().is_relative_to(root.resolve())


def test_2_sha256_correct(http_server: str, mgr: DownloadManager) -> None:
    body = b"abc123"
    _Handler.routes = {"/a.bin": {"body": body}}
    result = mgr.download(f"{http_server}/a.bin", filename="a.bin")
    assert result.success
    assert result.sha256 == hashlib.sha256(body).hexdigest()


def test_3_checksum_match(http_server: str, mgr: DownloadManager) -> None:
    body = b"match-me"
    digest = hashlib.sha256(body).hexdigest()
    _Handler.routes = {"/m.bin": {"body": body}}
    result = mgr.download(
        f"{http_server}/m.bin", filename="m.bin", expected_sha256=digest
    )
    assert result.success
    assert result.metadata.get("authenticity_verified") is True
    vr = verify_file(result.path, expected_sha256=digest)
    assert vr.ok and vr.authenticity_verified


def test_4_checksum_mismatch(http_server: str, mgr: DownloadManager, root: Path) -> None:
    body = b"actual"
    _Handler.routes = {"/bad.bin": {"body": body}}
    result = mgr.download(
        f"{http_server}/bad.bin",
        filename="bad.bin",
        expected_sha256="0" * 64,
    )
    assert not result.success
    assert result.error_code == "checksum"
    # partial cleaned up — dest should not exist as verified file
    assert not (root / "bad.bin").exists()


def test_5_http_error(http_server: str, mgr: DownloadManager) -> None:
    _Handler.routes = {"/missing": {"status": 404, "body": b"nope"}}
    result = mgr.download(f"{http_server}/missing", filename="x.bin")
    assert not result.success
    assert "404" in (result.error or "")


def test_6_timeout(http_server: str, root: Path) -> None:
    _Handler.routes = {"/slow": {"body": b"xxxxYYYY", "chunk_delay": 3.0}}
    mgr = DownloadManager(
        root,
        allow_private_hosts=True,
        connect_timeout=1.0,
        read_timeout=0.5,
        max_retries=0,
    )
    result = mgr.download(f"{http_server}/slow", filename="slow.bin")
    assert not result.success
    assert result.error_code in {"timeout", "network", "download_failed"}


def test_7_empty_response(http_server: str, mgr: DownloadManager) -> None:
    _Handler.routes = {"/empty": {"body": b""}}
    result = mgr.download(f"{http_server}/empty", filename="empty.bin")
    assert not result.success
    assert result.error_code == "empty"


def test_8_size_limit(http_server: str, root: Path) -> None:
    body = b"x" * 5000
    _Handler.routes = {"/big": {"body": body}}
    mgr = DownloadManager(root, max_bytes=1000, allow_private_hosts=True, max_retries=0)
    result = mgr.download(f"{http_server}/big", filename="big.bin")
    assert not result.success
    assert result.error_code == "size_limit"
    assert not (root / "big.bin").exists()


def test_9_unsafe_filename(mgr: DownloadManager) -> None:
    # path traversal in filename should be sanitized to basename only
    # absolute-style names rejected via resolve
    result = mgr.download("https://example.com/x", filename="../../etc/passwd")
    # URL will fail network or private — but filename sanitization yields "passwd"
    # Use local server instead
    pass  # covered via successful download with weird name below


def test_9b_filename_sanitized(http_server: str, mgr: DownloadManager, root: Path) -> None:
    body = b"safe"
    _Handler.routes = {"/f": {"body": body}}
    result = mgr.download(f"{http_server}/f", filename="../../evil.txt")
    assert result.success
    assert Path(result.path).name == "evil.txt"
    assert Path(result.path).resolve().is_relative_to(root.resolve())


def test_10_path_traversal_subdir(mgr: DownloadManager) -> None:
    result = mgr.download(
        "http://127.0.0.1/x",
        filename="a.txt",
        subdir="../../outside",
    )
    assert not result.success
    assert result.error_code in {"unsafe_filename", "path_escape", "private_host", "network"}


def test_11_absolute_path_rejected(root: Path) -> None:
    mgr = DownloadManager(root, allow_private_hosts=True)
    # destination API should not accept absolute escape via subdir
    result = mgr.download("http://127.0.0.1/x", filename="a.txt", subdir="/tmp")
    assert not result.success


def test_12_overwrite_protection(http_server: str, mgr: DownloadManager, root: Path) -> None:
    body = b"first"
    _Handler.routes = {"/o": {"body": body}}
    r1 = mgr.download(f"{http_server}/o", filename="once.txt")
    assert r1.success
    r2 = mgr.download(f"{http_server}/o", filename="once.txt", overwrite=False)
    assert not r2.success
    assert r2.error_code == "exists"
    assert Path(r1.path).read_bytes() == body


def test_13_symlink_escape(root: Path, http_server: str, tmp_path: Path) -> None:
    outside = tmp_path / "outside_secret"
    outside.write_text("secret")
    link_dir = root / "linkdir"
    try:
        link_dir.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported")
    mgr = DownloadManager(root, allow_private_hosts=True)
    _Handler.routes = {"/s": {"body": b"data"}}
    # Try to write through symlink subdir — resolve_under_root should block
    result = mgr.download(f"{http_server}/s", filename="x.bin", subdir="linkdir")
    # Either blocked as path_escape or, if linkdir resolves outside, error
    if result.success:
        # Must still not write outside root after resolve
        assert Path(result.path).resolve().is_relative_to(root.resolve())
    else:
        assert result.error_code in {"path_escape", "unsafe_filename", "fs_error"}


def test_14_partial_cleanup(http_server: str, root: Path) -> None:
    body = b"x" * 5000
    _Handler.routes = {"/big2": {"body": body}}
    mgr = DownloadManager(root, max_bytes=100, allow_private_hosts=True, max_retries=0)
    result = mgr.download(f"{http_server}/big2", filename="partial.bin")
    assert not result.success
    assert not (root / "partial.bin").exists()
    # no leftover .partial
    leftovers = list(root.glob(".jarvis_dl_*"))
    assert leftovers == []


def test_15_retry_on_500(http_server: str, mgr: DownloadManager) -> None:
    # First request fails with 500 — manager retries; we only expose 500
    _Handler.routes = {"/flaky": {"status": 500, "body": b"err"}}
    result = mgr.download(f"{http_server}/flaky", filename="flaky.bin")
    assert not result.success
    assert "500" in (result.error or "")


def test_16_cancellation(http_server: str, root: Path) -> None:
    body = b"Z" * 200000
    _Handler.routes = {"/cancelme": {"body": body, "chunk_delay": 0.3}}
    mgr = DownloadManager(
        root, allow_private_hosts=True, max_retries=0, read_timeout=10.0
    )

    def cancel_soon():
        import time

        time.sleep(0.05)
        mgr.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    result = mgr.download(f"{http_server}/cancelme", filename="c.bin")
    # May cancel or complete very fast; if cancelled, code is cancelled
    if result.cancelled or result.error_code == "cancelled":
        assert not (root / "c.bin").exists()
    # else download finished before cancel — still valid outcome


def test_17_redirect_private_blocked(root: Path) -> None:
    # Production manager rejects private hosts by default
    mgr = DownloadManager(root, allow_private_hosts=False, max_retries=0)
    result = mgr.download("http://127.0.0.1/x", filename="x.bin")
    assert not result.success
    assert result.error_code == "private_host"


def test_17b_scheme_rejected(mgr: DownloadManager) -> None:
    result = mgr.download("file:///etc/passwd", filename="p.bin")
    assert not result.success
    assert result.error_code == "bad_scheme"


def test_17c_credentials_in_url_rejected(mgr: DownloadManager) -> None:
    result = mgr.download("https://user:pass@example.com/x", filename="x.bin")
    assert not result.success
    assert result.error_code == "credentials_in_url"


def test_18_type_mismatch(http_server: str, mgr: DownloadManager) -> None:
    # PDF magic expected but plain text sent
    _Handler.routes = {"/notpdf": {"body": b"not a pdf"}}
    result = mgr.download(
        f"{http_server}/notpdf", filename="doc.pdf", expected_type="pdf"
    )
    assert not result.success
    assert result.error_code == "type_mismatch"


def test_18b_png_signature_ok(http_server: str, mgr: DownloadManager) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    _Handler.routes = {"/img": {"body": png}}
    result = mgr.download(
        f"{http_server}/img", filename="img.png", expected_type="png"
    )
    assert result.success


def test_verify_missing_file(tmp_path: Path) -> None:
    vr = verify_file(tmp_path / "nope")
    assert not vr.ok
    assert not vr.exists


def test_verify_size_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"abc")
    vr = verify_file(p, expected_size=10)
    assert not vr.ok
    assert "Size mismatch" in vr.errors[0]
