"""Phase 6F offline preparation tests. Do not prove sandbox isolation."""

from __future__ import annotations

import pytest

from jarvis.dev.execution_backend import (
    Approval,
    ArtifactError,
    ExecutionRequest,
    STATUS_BLOCKED,
    STATUS_MOCKED,
    STATUS_UNAVAILABLE,
    build_manifest,
    request_execution,
    validate_artifact_path,
)


def test_reject_traversal():
    with pytest.raises(ArtifactError):
        validate_artifact_path("../secret.py")
    with pytest.raises(ArtifactError):
        validate_artifact_path("/etc/passwd")


def test_reject_protected():
    with pytest.raises(ArtifactError):
        validate_artifact_path("jarvis_memory.db")
    with pytest.raises(ArtifactError):
        validate_artifact_path(".env")
    with pytest.raises(ArtifactError):
        validate_artifact_path("keys/id_rsa")


def test_manifest_hash():
    m = build_manifest(
        [{"path": "src/core.py", "content": "x = 1\n"}],
        manifest_id="m1",
    )
    assert m.files[0].sha256
    assert m.fingerprint()


def test_unknown_backend():
    m = build_manifest([{"path": "src/a.py", "content": "a=1\n"}], manifest_id="m")
    r = request_execution(ExecutionRequest(backend="other", manifest=m))
    assert r.status == STATUS_UNAVAILABLE
    assert r.code_executed is False


def test_real_backend_blocked():
    m = build_manifest([{"path": "src/a.py", "content": "a=1\n"}], manifest_id="m")
    r = request_execution(ExecutionRequest(backend="xai_code_execution", manifest=m))
    assert r.status == STATUS_BLOCKED
    assert r.code_executed is False


def test_approval_required():
    m = build_manifest([{"path": "src/a.py", "content": "a=1\n"}], manifest_id="m")
    r = request_execution(ExecutionRequest(backend="mock", manifest=m))
    assert r.status == STATUS_BLOCKED
    assert r.reason == "approval_missing"


def test_manifest_mismatch():
    m = build_manifest([{"path": "src/a.py", "content": "a=1\n"}], manifest_id="m")
    r = request_execution(
        ExecutionRequest(
            backend="mock",
            manifest=m,
            approval=Approval(
                manifest_fingerprint="deadbeef",
                backend="mock",
                approved=True,
            ),
        )
    )
    assert r.status == STATUS_BLOCKED
    assert r.reason == "manifest_changed"


def test_mock_does_not_execute():
    m = build_manifest([{"path": "src/a.py", "content": "a=1\n"}], manifest_id="m")
    r = request_execution(
        ExecutionRequest(
            backend="mock",
            manifest=m,
            approval=Approval(
                manifest_fingerprint=m.fingerprint(),
                backend="mock",
                approved=True,
            ),
        )
    )
    assert r.status == STATUS_MOCKED
    assert r.code_executed is False
    assert "Not real execution" in r.notes
