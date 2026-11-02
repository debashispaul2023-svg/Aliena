"""Phase 6I: template registry and consistency tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.codegen import propose_changes, GenerationError
from jarvis.dev.intelligence import detect_project_type
from jarvis.dev.models import SPEC_READY
from jarvis.dev.stages import analyze_requirements, design_architecture, build_plan
from jarvis.dev.templates import TEMPLATES, is_supported


def _ready(request: str):
    r = analyze_requirements(request)
    assert r.spec is not None
    r.spec.status = SPEC_READY
    r.spec.clarifying_questions = []
    a = design_architecture(r.spec)
    p = build_plan(r.spec, a.design)
    return r.spec, a.design, p.plan


def test_supported_inventory():
    assert is_supported("function")
    assert is_supported("library")
    assert is_supported("cli")
    assert is_supported("generic") is False
    assert TEMPLATES["function"]["files"]


def test_function_template_files():
    spec, design, plan = _ready("Language is Python. Build a hello function with unit tests.")
    changes = propose_changes(spec, design, plan)
    paths = [c.path for c in changes]
    assert "src/core.py" in paths
    assert "tests/test_core.py" in paths
    assert "TEMPLATE = 'function'" in changes[0].content


def test_unsupported_generic():
    spec, design, plan = _ready("Language is Python. Build a widget with unit tests.")
    assert detect_project_type(spec.user_request) == "generic"
    with pytest.raises(GenerationError):
        propose_changes(spec, design, plan)


def test_cli_template():
    spec, design, plan = _ready("Language is Python. Build a CLI that lists files with unit tests.")
    changes = propose_changes(spec, design, plan)
    assert changes
    assert any("TEMPLATE = 'cli'" in c.content for c in changes)
    assert any(c.path == "src/cli.py" for c in changes)
