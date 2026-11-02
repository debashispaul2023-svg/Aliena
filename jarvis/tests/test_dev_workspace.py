"""Phase 6B: development models + path-confined workspace tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.dev import (
    AcceptanceCriterion,
    RequirementSpec,
    DesignDoc,
    ChangeSet,
    ModelValidationError,
    WorkspaceManager,
    DevWorkspace,
    WorkspaceError,
    CRITERION_PENDING,
    CRITERION_PASS,
    CRITERION_FAIL,
    CHANGE_DRAFT,
    SPEC_DRAFT,
)


# ---------- models ----------

def test_1_valid_model_creation():
    ac = AcceptanceCriterion(description="Returns 200 on health check")
    assert ac.status == CRITERION_PENDING
    assert ac.criterion_id.startswith("ac_")
    spec = RequirementSpec(
        user_request="Build a health endpoint",
        functional=["GET /health returns 200"],
        acceptance_criteria=[ac],
    )
    assert spec.project_id.startswith("proj_")
    assert spec.status == SPEC_DRAFT
    design = DesignDoc(project_id=spec.project_id, overview="Minimal API")
    assert design.project_id == spec.project_id
    cs = ChangeSet(project_id=spec.project_id, changed_files=["app.py"])
    assert cs.status == CHANGE_DRAFT


def test_2_invalid_model_rejection():
    with pytest.raises(ModelValidationError):
        AcceptanceCriterion(description="")
    with pytest.raises(ModelValidationError):
        AcceptanceCriterion(description="x", status="NOT_A_STATUS")
    with pytest.raises(ModelValidationError):
        RequirementSpec(user_request="")
    with pytest.raises(ModelValidationError):
        DesignDoc(project_id="")
    with pytest.raises(ModelValidationError):
        ChangeSet(project_id="p", status="NOPE")


def test_3_serialization_round_trip():
    ac = AcceptanceCriterion(
        description="Unit tests pass",
        verification_method="unit_test",
        status=CRITERION_PASS,
        evidence_ref="tests/test_x.py",
    )
    spec = RequirementSpec(
        user_request="Feature X",
        functional=["A", "B"],
        non_functional=["fast"],
        constraints=["stdlib only"],
        assumptions=["Python 3.10+"],
        clarifying_questions=["Target OS?"],
        acceptance_criteria=[ac],
        metadata={"priority": "high"},
    )
    data = spec.to_dict()
    blob = json.dumps(data)
    restored = RequirementSpec.from_dict(json.loads(blob))
    assert restored.user_request == spec.user_request
    assert restored.functional == ["A", "B"]
    assert restored.acceptance_criteria[0].status == CRITERION_PASS
    assert restored.acceptance_criteria[0].evidence_ref == "tests/test_x.py"
    assert restored.metadata["priority"] == "high"

    design = DesignDoc(
        project_id=spec.project_id,
        overview="svc",
        components=[{"name": "api"}],
        decisions=["Use Flask"],
        security_considerations=["No shell"],
    )
    d2 = DesignDoc.from_dict(design.to_dict())
    assert d2.components[0]["name"] == "api"

    cs = ChangeSet(
        project_id=spec.project_id,
        changed_files=["a.py"],
        summaries=["add endpoint"],
        related_criteria=[ac.criterion_id],
        test_evidence=["pytest exit 0"],
    )
    cs2 = ChangeSet.from_dict(cs.to_dict())
    assert cs2.changed_files == ["a.py"]
    assert cs2.related_criteria == [ac.criterion_id]


def test_4_criterion_status_validation():
    ac = AcceptanceCriterion(description="ok", status=CRITERION_FAIL)
    assert ac.status == CRITERION_FAIL
    with pytest.raises(ModelValidationError):
        AcceptanceCriterion(description="ok", status="SUCCESS")  # not in enum


# ---------- workspace ----------

@pytest.fixture
def mgr(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(tmp_path / "dev_workspaces")


def test_5_project_creation(mgr: WorkspaceManager):
    ws = mgr.create_project("demo_app")
    assert ws.project_root.exists()
    assert ws.project_name == "demo_app"
    assert "demo_app" in mgr.list_projects()
    ws2 = mgr.open_project("demo_app")
    assert ws2.project_root == ws.project_root


def test_6_safe_relative_resolve(mgr: WorkspaceManager):
    ws = mgr.create_project("proj1")
    p = ws.resolve("src/main.py")
    assert p.name == "main.py"
    assert ws.contains(p)


def test_7_path_traversal_rejected(mgr: WorkspaceManager):
    ws = mgr.create_project("proj2")
    with pytest.raises(WorkspaceError) as ei:
        ws.resolve("../secret.txt")
    assert ei.value.code == "traversal"
    with pytest.raises(WorkspaceError):
        ws.resolve("foo/../../etc/passwd")


def test_8_absolute_path_rejected(mgr: WorkspaceManager):
    ws = mgr.create_project("proj3")
    with pytest.raises(WorkspaceError) as ei:
        ws.resolve("/etc/passwd")
    assert ei.value.code == "absolute_path"


def test_9_symlink_escape(mgr: WorkspaceManager, tmp_path: Path):
    ws = mgr.create_project("proj_link")
    outside = tmp_path / "outside_secret"
    outside.write_text("secret")
    link = ws.project_root / "leak"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not supported")
    with pytest.raises(WorkspaceError) as ei:
        ws.resolve("leak")
    assert ei.value.code in {"symlink_escape", "path_escape"}


def test_10_safe_read_write(mgr: WorkspaceManager):
    ws = mgr.create_project("proj_rw")
    path = ws.write_text("hello.txt", "world")
    assert path.exists()
    assert ws.read_text("hello.txt") == "world"
    ws.write_bytes("data.bin", b"\x00\x01")
    assert ws.read_bytes("data.bin") == b"\x00\x01"
    assert "hello.txt" in ws.list_files()


def test_11_overwrite_protection(mgr: WorkspaceManager):
    ws = mgr.create_project("proj_ow")
    ws.write_text("a.txt", "one")
    with pytest.raises(WorkspaceError) as ei:
        ws.write_text("a.txt", "two", overwrite=False)
    assert ei.value.code == "exists"
    assert ws.read_text("a.txt") == "one"
    ws.write_text("a.txt", "two", overwrite=True)
    assert ws.read_text("a.txt") == "two"


def test_12_temp_cleanup_on_failure(mgr: WorkspaceManager, monkeypatch):
    ws = mgr.create_project("proj_tmp")
    # Force failure after temp create by making replace fail
    real_replace = __import__("os").replace

    def boom(src, dst):
        raise OSError("simulated failure")

    monkeypatch.setattr(__import__("os"), "replace", boom)
    with pytest.raises(OSError):
        ws.write_text("fail.txt", "data")
    # no leftover temps
    leftovers = list(ws.project_root.glob(".jarvis_ws_*"))
    assert leftovers == []
    assert not ws.exists("fail.txt")
    monkeypatch.setattr(__import__("os"), "replace", real_replace)


def test_13_project_isolation(mgr: WorkspaceManager):
    a = mgr.create_project("alpha")
    b = mgr.create_project("beta")
    a.write_text("only_a.txt", "A")
    b.write_text("only_b.txt", "B")
    assert a.list_files() == ["only_a.txt"]
    assert b.list_files() == ["only_b.txt"]
    with pytest.raises(WorkspaceError):
        a.read_text("../beta/only_b.txt")


def test_14_preserve_unrelated(mgr: WorkspaceManager):
    ws = mgr.create_project("preserve")
    ws.write_text("keep.txt", "important")
    ws.write_text("other.txt", "x")
    ws.write_text("other.txt", "y", overwrite=True)
    assert ws.read_text("keep.txt") == "important"


def test_15_unsafe_project_names(mgr: WorkspaceManager):
    for bad in ["", "..", "../x", "a/b", "has space", ".hidden", "-bad"]:
        with pytest.raises(WorkspaceError):
            mgr.create_project(bad)


def test_open_missing_project(mgr: WorkspaceManager):
    with pytest.raises(WorkspaceError) as ei:
        mgr.open_project("no_such_project")
    assert ei.value.code == "not_found"


def test_nested_write(mgr: WorkspaceManager):
    ws = mgr.create_project("nested")
    ws.write_text("src/pkg/mod.py", "print(1)\n")
    assert ws.read_text("src/pkg/mod.py") == "print(1)\n"
    files = ws.list_files()
    assert "src/pkg/mod.py" in files


def test_symlink_dir_write_list_mkdir_blocked(mgr: WorkspaceManager, tmp_path: Path):
    """Symlink directory must not allow write, list, or mkdir outside the jail."""
    ws = mgr.create_project("linkdir")
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET")
    link = ws.project_root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not supported")
    with pytest.raises(WorkspaceError):
        ws.write_text("linked/injected.txt", "pwned")
    with pytest.raises(WorkspaceError):
        ws.list_files("linked")
    with pytest.raises(WorkspaceError):
        ws.mkdir("linked/subdir")
    assert not (outside / "injected.txt").exists()
    assert not (outside / "subdir").exists()
    assert (outside / "secret.txt").read_text() == "SECRET"


def test_symlink_file_write_blocked(mgr: WorkspaceManager, tmp_path: Path):
    ws = mgr.create_project("linkfile")
    outside = tmp_path / "outside_file.txt"
    outside.write_text("orig")
    link = ws.project_root / "filelink"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not supported")
    with pytest.raises(WorkspaceError):
        ws.write_text("filelink", "pwned", overwrite=True)
    assert outside.read_text() == "orig"


def test_windows_style_traversal(mgr: WorkspaceManager):
    ws = mgr.create_project("wintrav")
    with pytest.raises(WorkspaceError) as ei:
        ws.resolve("..\\secret")
    assert ei.value.code == "traversal"
    with pytest.raises(WorkspaceError):
        ws.resolve("foo\\..\\..\\etc\\passwd")


def test_missing_file_behavior(mgr: WorkspaceManager):
    ws = mgr.create_project("missing")
    with pytest.raises(WorkspaceError) as ei:
        ws.read_text("nope.txt")
    assert ei.value.code == "not_found"
    with pytest.raises(WorkspaceError) as ei:
        ws.read_bytes("nope.bin")
    assert ei.value.code == "not_found"
    assert ws.exists("nope.txt") is False


def test_malformed_model_from_dict():
    with pytest.raises(ModelValidationError):
        RequirementSpec.from_dict("not-a-dict")  # type: ignore
    with pytest.raises(ModelValidationError):
        AcceptanceCriterion.from_dict({"description": "x", "status": "BOGUS"})
    with pytest.raises(ModelValidationError):
        DesignDoc.from_dict([])  # type: ignore
    with pytest.raises(ModelValidationError):
        ChangeSet.from_dict({"project_id": "p", "status": "INVALID"})


def test_failed_op_does_not_touch_outside(mgr: WorkspaceManager, tmp_path: Path):
    ws = mgr.create_project("safe")
    outside = tmp_path / "untouched.txt"
    outside.write_text("keep-me")
    with pytest.raises(WorkspaceError):
        ws.write_text("../untouched.txt", "changed")
    assert outside.read_text() == "keep-me"
