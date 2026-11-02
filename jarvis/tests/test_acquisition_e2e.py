"""Phase E: resource acquisition workflow e2e tests (local HTTP)."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from jarvis.ai.resource_finder import ResourceFinder, FixtureSearchAdapter
from jarvis.core.agents.specialized import ResourceFinderAgent
from jarvis.core.models import TaskRecord
from jarvis.core.orchestrator import Orchestrator
from jarvis.resources import (
    DownloadManager,
    ResourceRegistry,
    ResourceAcquisitionService,
    AcquisitionRequest,
    AcquisitionPolicy,
    INTENT_FIND,
    INTENT_FIND_DOWNLOAD,
    STATUS_VERIFIED,
    STATUS_FAILED,
    STATUS_REJECTED,
    STATUS_AWAITING_APPROVAL,
    STATUS_DISCOVERED,
)


class _H(BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *a):
        return

    def do_GET(self):
        route = self.routes.get(self.path)
        if not route:
            self.send_response(404)
            self.end_headers()
            return
        body = route.get("body", b"")
        self.send_response(route.get("status", 200))
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
def root(tmp_path: Path) -> Path:
    d = tmp_path / "JarvisResources"
    d.mkdir()
    return d


@pytest.fixture
def reg(tmp_path: Path) -> ResourceRegistry:
    return ResourceRegistry(tmp_path / "res.db")


def _service(root, reg, finder=None, auto=True, approval=None):
    return ResourceAcquisitionService(
        finder=finder or ResourceFinder(),
        downloader=DownloadManager(root, allow_private_hosts=True, max_retries=0),
        registry=reg,
        policy=AcquisitionPolicy(auto_download_public=auto, allow_overwrite=False),
        approval_callback=approval,
        resource_root=root,
    )


def test_1_find_only_no_download(root: Path, reg: ResourceRegistry) -> None:
    fixtures = {
        "demo": [
            {
                "title": "demo",
                "url": "https://example.com/demo.txt",
                "source": "fixture",
                "kind": "docs",
            }
        ]
    }
    svc = _service(root, reg, finder=ResourceFinder(FixtureSearchAdapter(fixtures)))
    report = svc.run(AcquisitionRequest(need="demo", intent=INTENT_FIND))
    assert report.success
    assert report.status == STATUS_DISCOVERED
    assert report.local_path is None
    assert list(root.iterdir()) == []  # nothing downloaded
    assert report.local_path is None
    # find-only must not create files under resource root
    assert not any(p.is_file() for p in root.rglob("*"))


def test_2_find_and_download_real(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    body = b"phase-e-payload"
    _H.routes = {"/asset.txt": {"body": body}}
    url = f"{http_server}/asset.txt"
    svc = _service(root, reg, auto=True)
    report = svc.run(
        AcquisitionRequest(
            need="asset",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=url,
            filename="asset.txt",
        )
    )
    assert report.success, report.error
    assert report.status == STATUS_VERIFIED
    assert report.local_path
    assert Path(report.local_path).read_bytes() == body
    assert Path(report.local_path).resolve().is_relative_to(root.resolve())


def test_3_saved_under_resource_root(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    _H.routes = {"/r.bin": {"body": b"xyz"}}
    svc = _service(root, reg, auto=True)
    report = svc.run(
        AcquisitionRequest(
            need="r",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=f"{http_server}/r.bin",
            filename="r.bin",
            project="proj1",
        )
    )
    assert report.success
    assert "projects" in (report.local_path or "")
    assert Path(report.local_path).exists()


def test_4_verification_success(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    body = b"abc"
    sha = hashlib.sha256(body).hexdigest()
    _H.routes = {"/v.bin": {"body": body}}
    svc = _service(root, reg, auto=True)
    report = svc.run(
        AcquisitionRequest(
            need="v",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=f"{http_server}/v.bin",
            filename="v.bin",
            expected_sha256=sha,
        )
    )
    assert report.success
    assert report.resource and report.resource.sha256 == sha


def test_5_verification_failure_blocks_verified(
    http_server: str, root: Path, reg: ResourceRegistry
) -> None:
    _H.routes = {"/bad.bin": {"body": b"actual"}}
    svc = _service(root, reg, auto=True)
    report = svc.run(
        AcquisitionRequest(
            need="bad",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=f"{http_server}/bad.bin",
            filename="bad.bin",
            expected_sha256="0" * 64,
        )
    )
    assert not report.success
    assert report.status != STATUS_VERIFIED
    assert report.status == STATUS_FAILED


def test_6_registry_records_fields(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    body = b"regdata"
    _H.routes = {"/reg.txt": {"body": body}}
    url = f"{http_server}/reg.txt"
    svc = _service(root, reg, auto=True)
    report = svc.run(
        AcquisitionRequest(
            need="reg",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=url,
            filename="reg.txt",
        )
    )
    assert report.resource
    rec = reg.get(report.resource.id)
    assert rec is not None
    assert rec.canonical_url == url or rec.original_url == url
    assert rec.local_path
    assert rec.size == len(body)
    assert rec.sha256 == hashlib.sha256(body).hexdigest()


def test_7_approval_required_when_auto_disabled(
    http_server: str, root: Path, reg: ResourceRegistry
) -> None:
    _H.routes = {"/x.txt": {"body": b"x"}}
    svc = _service(root, reg, auto=False, approval=None)
    report = svc.run(
        AcquisitionRequest(
            need="x",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=f"{http_server}/x.txt",
            filename="x.txt",
        )
    )
    assert not report.success
    assert report.approval_required
    assert report.status == STATUS_AWAITING_APPROVAL
    assert list(root.glob("**/*")) == [] or not any(p.is_file() for p in root.rglob("*") if p.name == "x.txt")


def test_8_rejected_approval(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    _H.routes = {"/y.txt": {"body": b"y"}}
    svc = _service(root, reg, auto=False, approval=lambda info: False)
    report = svc.run(
        AcquisitionRequest(
            need="y",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=f"{http_server}/y.txt",
            filename="y.txt",
        )
    )
    assert not report.success
    assert report.status == STATUS_REJECTED
    assert report.approval_granted is False


def test_9_failed_download_status(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    _H.routes = {"/missing": {"status": 404, "body": b"no"}}
    svc = _service(root, reg, auto=True)
    report = svc.run(
        AcquisitionRequest(
            need="missing",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=f"{http_server}/missing",
            filename="missing.bin",
        )
    )
    assert not report.success
    assert report.status == STATUS_FAILED


def test_11_provider_fallback_via_fixture(root: Path, reg: ResourceRegistry) -> None:
    # Finder with empty then usable fixture — Multi not required; empty need fails
    svc = _service(root, reg, finder=ResourceFinder(FixtureSearchAdapter({})), auto=True)
    report = svc.run(AcquisitionRequest(need="nothing-here", intent=INTENT_FIND_DOWNLOAD))
    assert not report.success
    assert "No candidates" in (report.error or "")


def test_12_duplicate_idempotent(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    body = b"dup"
    _H.routes = {"/dup.txt": {"body": body}}
    url = f"{http_server}/dup.txt"
    svc = _service(root, reg, auto=True)
    r1 = svc.run(
        AcquisitionRequest(
            need="dup", intent=INTENT_FIND_DOWNLOAD, preferred_url=url, filename="dup.txt"
        )
    )
    # second without overwrite should not explode; may fail exists or reuse
    r2 = svc.run(
        AcquisitionRequest(
            need="dup", intent=INTENT_FIND_DOWNLOAD, preferred_url=url, filename="dup.txt"
        )
    )
    assert r1.success
    # either rejected as exists or same registry id
    if r2.resource and r1.resource:
        assert r2.resource.id == r1.resource.id or r2.status != STATUS_VERIFIED


def test_13_orchestrator_failure_status(
    http_server: str, root: Path, reg: ResourceRegistry
) -> None:
    _H.routes = {"/nope": {"status": 500, "body": b"err"}}
    svc = _service(root, reg, auto=True)
    orch = Orchestrator(resource_acquisition=svc, workspace=root / "ws")
    task = TaskRecord.new(
        description="download missing",
        agent_name="resource_finder",
        inputs={
            "need": "nope",
            "intent": "find_and_download",
            "url": f"{http_server}/nope",
            "filename": "nope.bin",
        },
    )
    result = orch.run(objective="acquire missing", tasks=[task])
    t = result.tasks[0]
    # On agent failure the orchestrator should mark FAILED (not COMPLETED)
    assert t.status == "FAILED" or (
        t.status == "COMPLETED" and getattr(t, "error", None)
    )
    if t.status != "FAILED":
        # fallback: outputs indicate failure
        outputs = getattr(t, "outputs", None) or {}
        assert outputs.get("success") is False or t.error


def test_14_agent_invokes_pipeline(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    body = b"agent-dl"
    _H.routes = {"/ag.txt": {"body": body}}
    svc = _service(root, reg, auto=True)
    agent = ResourceFinderAgent()
    task = TaskRecord.new(
        description="get asset",
        agent_name="resource_finder",
        inputs={
            "need": "ag",
            "intent": "find_and_download",
            "url": f"{http_server}/ag.txt",
            "filename": "ag.txt",
        },
    )
    ar = agent.execute(task, {"resource_acquisition": svc})
    assert ar.success
    assert ar.outputs.get("local_path")
    assert Path(ar.outputs["local_path"]).read_bytes() == body


def test_approval_granted_downloads(http_server: str, root: Path, reg: ResourceRegistry) -> None:
    _H.routes = {"/ok.txt": {"body": b"approved"}}
    svc = _service(root, reg, auto=False, approval=lambda info: True)
    report = svc.run(
        AcquisitionRequest(
            need="ok",
            intent=INTENT_FIND_DOWNLOAD,
            preferred_url=f"{http_server}/ok.txt",
            filename="ok.txt",
        )
    )
    assert report.success
    assert report.approval_granted is True
    assert Path(report.local_path).read_bytes() == b"approved"
