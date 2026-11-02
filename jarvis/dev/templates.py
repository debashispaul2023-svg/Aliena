"""Deterministic template registry (Phase 6I).

Conservative coverage. Not a general code generator.
Does not execute generated code.
"""

from __future__ import annotations

from typing import Any

TEMPLATE_VERSION = "1.1"

TEMPLATES: dict[str, dict[str, Any]] = {
    "function": {
        "id": "function",
        "version": TEMPLATE_VERSION,
        "supported": True,
        "required_inputs": ["user_request"],
        "files": ["src/core.py", "tests/test_core.py", "README.md"],
        "entry_point": "src/core.py",
        "dependencies": [],
        "limitations": [
            "Stub implementation only.",
            "Not verified by execution.",
        ],
    },
    "library": {
        "id": "library",
        "version": TEMPLATE_VERSION,
        "supported": True,
        "required_inputs": ["user_request"],
        "files": ["src/__init__.py", "src/core.py", "tests/test_core.py", "README.md"],
        "entry_point": "src/__init__.py",
        "dependencies": [],
        "limitations": ["Package skeleton only. Not executed."],
    },
    "cli": {
        "id": "cli",
        "version": TEMPLATE_VERSION,
        "supported": True,
        "required_inputs": ["user_request"],
        "files": ["src/__init__.py", "src/cli.py", "tests/test_cli.py", "README.md"],
        "entry_point": "src/cli.py",
        "dependencies": [],
        "limitations": ["Argparse skeleton only. Not executed."],
    },
    "generic": {
        "id": "generic",
        "version": TEMPLATE_VERSION,
        "supported": False,
        "required_inputs": ["user_request"],
        "files": [],
        "entry_point": None,
        "dependencies": [],
        "limitations": [
            "Unsupported for coherent generation.",
            "Classify the request more specifically.",
        ],
    },
}


def get_template(project_type: str) -> dict[str, Any]:
    return TEMPLATES.get(project_type, TEMPLATES["generic"])


def is_supported(project_type: str) -> bool:
    return bool(get_template(project_type).get("supported"))
