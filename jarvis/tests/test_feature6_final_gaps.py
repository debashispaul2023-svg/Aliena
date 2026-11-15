"""Feature 6 final gap tests. Controlled fixtures only."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jarvis.resources.downloader import DownloadError, DownloadManager, validate_url


class SlowHandler(BaseHTTPRequestHandler):
    delay = 0
    body = b"payload"

    def do_GET(self):
        if self.delay:
            import time
            time.sleep(self.delay)
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, fmt, *args):
        return


@pytest.fixture()
def local_server():
    SlowHandler.delay = 0
    SlowHandler.body = b"payload"
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def test_dns_rebind_fixture_blocks_later_private(monkeypatch):
    """First resolve looks public; later resolve is restricted. Must fail closed."""
    calls = {"n": 0}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    # First check may pass; second must see the restricted address.
    first = validate_url("https://rebind.example/file")
    assert first.startswith("https://")
    with pytest.raises(DownloadError):
        validate_url("https://rebind.example/file")


def test_concurrent_downloads_and_filename_lock(tmp_path: Path, local_server):
    port = local_server.server_address[1]
    url = f"http://127.0.0.1:{port}/item"
    mgr = DownloadManager(tmp_path, allow_private_hosts=True, max_retries=0)
    results = []

    def worker(name):
        results.append(mgr.download(url, filename=name))

    threads = [
        threading.Thread(target=worker, args=(f"file{i}.bin",))
        for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    ok = [r for r in results if r.success]
    assert len(ok) == 3
    for item in ok:
        assert Path(item.path).read_bytes() == b"payload"
    assert list(tmp_path.glob("*.partial")) == []

    # Same destination must not race into a double write.
    collision = []
    threads = [
        threading.Thread(target=lambda: collision.append(mgr.download(url, filename="same.bin")))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    codes = sorted(r.error_code or "ok" for r in collision)
    assert "ok" in codes
    assert "locked" in codes or "exists" in codes


def test_read_timeout_cleans_partial(tmp_path: Path, local_server):
    SlowHandler.delay = 2
    port = local_server.server_address[1]
    mgr = DownloadManager(
        tmp_path,
        allow_private_hosts=True,
        connect_timeout=1,
        read_timeout=0.2,
        max_retries=0,
    )
    result = mgr.download(f"http://127.0.0.1:{port}/slow", filename="slow.bin")
    assert result.success is False
    assert result.error_code == "timeout"
    assert list(tmp_path.glob("*.partial")) == []


def test_connect_timeout_reports_timeout(tmp_path: Path):
    mgr = DownloadManager(
        tmp_path,
        allow_private_hosts=True,
        connect_timeout=0.2,
        read_timeout=0.2,
        max_retries=0,
    )
    # Closed port on localhost: controlled, not a real internal probe.
    result = mgr.download("http://127.0.0.1:1/none", filename="none.bin")
    assert result.success is False
    assert result.error_code in {"timeout", "network"}
    assert list(tmp_path.glob("*.partial")) == []
