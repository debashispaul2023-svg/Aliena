"""Feature 6 remaining verification gaps. Local fixtures only."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jarvis.resources.downloader import DownloadError, DownloadManager, validate_url, _is_private_or_local


class _Handler(BaseHTTPRequestHandler):
    delay = 0
    status = 200
    body = b"ok"
    fail_times = 0
    calls = 0

    def do_GET(self):
        type(self).calls += 1
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1/private")
            self.end_headers()
            return
        if type(self).calls <= type(self).fail_times:
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        if self.delay:
            import time
            time.sleep(self.delay)
        self.wfile.write(self.body)

    def log_message(self, fmt, *args):
        return


@pytest.fixture()
def local_server():
    _Handler.calls = 0
    _Handler.fail_times = 0
    _Handler.delay = 0
    _Handler.body = b"hello-feature6"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def test_restricted_ipv4_and_ipv6():
    blocked = [
        "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1",
        "169.254.169.254", "0.0.0.0", "255.255.255.255", "224.0.0.1",
        "::1", "fc00::1", "fe80::1", "2001:db8::1",
    ]
    for host in blocked:
        assert _is_private_or_local(host) is True
    for url in ("file:///etc/passwd", "ftp://example.com/x"):
        with pytest.raises(DownloadError):
            validate_url(url)


def test_redirect_to_private_rejected(tmp_path: Path):
    class FakeResp:
        url = "http://127.0.0.1/private"
        history = [type("H", (), {"url": "https://example.com/start"})()]
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, chunk_size=1):
            yield b"x"

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResp()

    mgr = DownloadManager(tmp_path, session=FakeSession(), allow_private_hosts=False)
    result = mgr.download("https://example.com/start", filename="out.bin")
    assert result.success is False
    assert result.error_code == "bad_redirect"


def test_cancel_during_download(tmp_path: Path, local_server):
    _Handler.delay = 2
    port = local_server.server_address[1]
    mgr = DownloadManager(tmp_path, allow_private_hosts=True, connect_timeout=1, read_timeout=5)

    def cancel_soon():
        import time
        time.sleep(0.2)
        mgr.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    result = mgr.download(f"http://127.0.0.1:{port}/slow", filename="slow.bin")
    assert result.cancelled is True
    assert not any(tmp_path.glob("*.partial"))


def test_retry_after_transient(tmp_path: Path, local_server):
    _Handler.fail_times = 1
    port = local_server.server_address[1]
    mgr = DownloadManager(tmp_path, allow_private_hosts=True, max_retries=2)
    result = mgr.download(f"http://127.0.0.1:{port}/ok", filename="retry.bin")
    assert result.success is True
    assert result.metadata["attempts"] >= 2


def test_partial_cleaned_on_cancel(tmp_path: Path, local_server):
    _Handler.delay = 2
    port = local_server.server_address[1]
    mgr = DownloadManager(tmp_path, allow_private_hosts=True)

    def cancel_soon():
        import time
        time.sleep(0.2)
        mgr.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    mgr.download(f"http://127.0.0.1:{port}/slow", filename="partial.bin")
    assert list(tmp_path.glob("*.partial")) == []


def test_disk_full_reported(tmp_path: Path, monkeypatch):
    import jarvis.resources.downloader as dl
    monkeypatch.setattr(dl.shutil, "disk_usage", lambda path: type("U", (), {"free": 0})())
    mgr = DownloadManager(tmp_path)
    result = mgr.download("https://example.com/file.txt", filename="x.txt")
    assert result.success is False
    assert result.error_code == "disk_full"
