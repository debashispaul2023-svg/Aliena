"""Phase 6J: template implementation quality tests. Does not execute generated code."""

from __future__ import annotations

from jarvis.dev.codegen import propose_changes
from jarvis.dev.models import SPEC_READY
from jarvis.dev.stages import analyze_requirements, design_architecture, build_plan


def _ready(request: str):
    r = analyze_requirements(request)
    r.spec.status = SPEC_READY
    r.spec.clarifying_questions = []
    a = design_architecture(r.spec)
    p = build_plan(r.spec, a.design)
    return r.spec, a.design, p.plan


def test_function_has_signature():
    spec, design, plan = _ready("Language is Python. Build a hello function with unit tests.")
    changes = propose_changes(spec, design, plan)
    core = next(c for c in changes if c.path == "src/core.py")
    assert "def hello" in core.content
    assert "PLACEHOLDER = True" in core.content


def test_library_public_api():
    spec, design, plan = _ready("Language is Python. Build a library package with unit tests.")
    changes = propose_changes(spec, design, plan)
    init = next(c for c in changes if c.path == "src/__init__.py")
    assert "public_api" in init.content
    assert "__all__" in init.content


def test_cli_entry_point():
    spec, design, plan = _ready("Language is Python. Build a CLI that lists files with unit tests.")
    changes = propose_changes(spec, design, plan)
    cli = next(c for c in changes if c.path == "src/cli.py")
    assert "argparse" in cli.content
    assert "def main" in cli.content
    assert "PLACEHOLDER = True" in cli.content
