"""Phase F: natural-language resource command routing tests."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from jarvis.ai.resource_finder import FixtureSearchAdapter, ResourceFinder
from jarvis.resources import (
    AcquisitionPolicy,
    DownloadManager,
    ResourceAcquisitionService,
    ResourceRegistry,
)
from jarvis.resources.commands import (
    ResourceCommandHandler,
    parse_resource_command,
    format_report,
    list_resources_text,
    HELP_TEXT,
)
from jarvis.resources.acquisition import AcquisitionReport, INTENT_FIND


class _H(BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *a):
        return

    def do_GET(self):
        r = self.routes.get(self.path)
        if not r:
            self.send_response(404)
            self.end_headers()
            return
        body = r.get("body", b"")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def http_server():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture
def spoken(tmp_path):
    lines: list[str] = []

    def speak(t: str) -> None:
        lines.append(t)

    return lines, speak


@pytest.fixture
def handler(tmp_path, spoken):
    lines, speak = spoken
    root = tmp_path / "JarvisResources"
    root.mkdir()
    reg = ResourceRegistry(tmp_path / "r.db")
    fixtures = {
        "docs": [
            {
                "title": "Demo Docs",
                "url": "https://example.com/docs",
                "source": "fixture",
                "kind": "docs",
            }
        ]
    }
    svc = ResourceAcquisitionService(
        finder=ResourceFinder(FixtureSearchAdapter(fixtures)),
        downloader=DownloadManager(root, allow_private_hosts=True),
        registry=reg,
        policy=AcquisitionPolicy(auto_download_public=False),
        resource_root=root,
    )
    h = ResourceCommandHandler(service=svc, speak=speak)
    return h, lines, root, reg, svc


# ---- intent routing ----

@pytest.mark.parametrize(
    "query,intent",
    [
        ("find resources for requests library", "find"),
        ("find the official documentation", "find"),
        ("find and download the official documentation", "find_and_download"),
        ("download https://example.com/a.txt", "find_and_download"),
        ("khuje download requests", "find_and_download"),
        ("where did you save that file", "locate"),
        ("kothay save korle", "locate"),
        ("verify the file I downloaded", "verify"),
        ("alternative for requests", "alternative"),
    ],
)
def test_1_intent_routing(query, intent):
    p = parse_resource_command(query)
    assert p.handled
    assert p.intent == intent


def test_list_and_help():
    assert parse_resource_command("list resources").list_only
    assert parse_resource_command("resource help").help_text


def test_2_find_only_no_download(handler):
    h, lines, root, reg, svc = handler
    assert h.handle("find resources for docs")
    assert any("discovered only" in x.lower() or "candidate" in x.lower() for x in lines)
    assert not any(p.is_file() for p in root.rglob("*"))


def test_3_find_and_download_reaches_service(http_server, handler):
    h, lines, root, reg, svc = handler
    body = b"cmd-payload"
    _H.routes = {"/c.txt": {"body": body}}
    url = f"{http_server}/c.txt"
    # first: awaiting approval
    assert h.handle(f"download {url}")
    assert any("approval required" in x.lower() for x in lines)
    # approve
    lines.clear()
    assert h.handle("approve download")
    assert any("local path" in x.lower() or "downloaded" in x.lower() for x in lines)
    files = [p for p in root.rglob("*") if p.is_file()]
    assert files
    assert files[0].read_bytes() == body


def test_4_locate_path(handler, tmp_path):
    h, lines, root, reg, svc = handler
    # seed registry with a fake verified path
    f = root / "seed.txt"
    f.write_bytes(b"seed")
    from jarvis.resources import DownloadResult

    dl = DownloadResult(
        success=True,
        path=str(f),
        original_url="https://example.com/seed.txt",
        final_url="https://example.com/seed.txt",
        size=4,
        sha256=hashlib.sha256(b"seed").hexdigest(),
    )
    rec = reg.register_download(dl, title="seed.txt", source="test")
    lines.clear()
    assert h.handle("where did you save seed")
    assert any("seed" in x.lower() for x in lines)


def test_5_verify_missing(handler, tmp_path):
    h, lines, root, reg, svc = handler
    f = root / "gone.txt"
    f.write_bytes(b"x")
    from jarvis.resources import DownloadResult

    dl = DownloadResult(
        success=True,
        path=str(f),
        original_url="https://example.com/gone.txt",
        final_url="https://example.com/gone.txt",
        size=1,
        sha256=hashlib.sha256(b"x").hexdigest(),
    )
    reg.register_download(dl, title="gone.txt")
    f.unlink()
    lines.clear()
    assert h.handle("verify the file gone")
    assert any("fail" in x.lower() or "missing" in x.lower() for x in lines)


def test_6_list_resources(handler):
    h, lines, root, reg, svc = handler
    reg.register_discovered(title="Listed", url="https://example.com/l")
    lines.clear()
    assert h.handle("list resources")
    assert any("Listed" in x for x in lines)


def test_7_8_approval_and_reject(http_server, handler):
    h, lines, root, reg, svc = handler
    _H.routes = {"/z.txt": {"body": b"z"}}
    url = f"{http_server}/z.txt"
    assert h.handle(f"download {url}")
    assert any("approval" in x.lower() for x in lines)
    lines.clear()
    assert h.handle("reject download")
    assert any("reject" in x.lower() for x in lines)
    assert not any(p.name == "z.txt" for p in root.rglob("*") if p.is_file())


def test_9_ambiguous():
    p = parse_resource_command("download")
    assert p.handled and p.ambiguous


def test_10_ordinary_conversation_not_routed():
    assert not parse_resource_command("how is the weather today").handled
    assert not parse_resource_command("tell me a joke").handled
    assert not parse_resource_command("find file report.pdf").handled  # existing OS cmd
    assert not parse_resource_command("remember this is important").handled


def test_11_error_display(handler):
    h, lines, root, reg, svc = handler
    lines.clear()
    assert h.handle("find and download nothing-matching-xyz")
    # may await approval after empty search failure or report failure
    assert lines


def test_12_help_text(handler):
    h, lines, root, reg, svc = handler
    lines.clear()
    assert h.handle("resource help")
    assert any("download" in x.lower() for x in lines)


def test_format_report_find_only():
    rep = AcquisitionReport(
        success=True,
        intent=INTENT_FIND,
        status="DISCOVERED",
        need="x",
        candidates=[{"title": "T", "url": "https://e.com", "source": "pypi", "kind": "package"}],
        notes="no download",
    )
    text = format_report(rep)
    assert "downloaded" not in text.lower() or "nothing was downloaded" in text.lower()
    assert "install" not in text.lower() or "not install" in text.lower()
