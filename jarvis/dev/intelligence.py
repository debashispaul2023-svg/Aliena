"""Offline coding intelligence helpers (Phase 6H).

Deterministic rules only. Not an LLM. Does not execute generated code.
"""

from __future__ import annotations

import ast
from typing import Optional

from jarvis.dev.models import RequirementSpec
from jarvis.dev.workspace import DevWorkspace, WorkspaceError


_PROJECT_HINTS = {
    "cli": ("cli", "command line", "argparse"),
    "library": ("library", "package", "module"),
    "function": ("function", "hello", "add", "convert"),
}


def detect_project_type(request: str) -> str:
    low = (request or "").lower()
    for kind, hints in _PROJECT_HINTS.items():
        if any(h in low for h in hints):
            return kind
    return "generic"


def detect_contradictions(request: str) -> list[str]:
    low = (request or "").lower()
    issues: list[str] = []
    offline = "offline" in low
    network = any(tok in low for tok in ("must use network", "use the network", "requires network", "network access"))
    if offline and network:
        issues.append("Contradiction: offline and network access.")
    if "no database" in low and any(tok in low for tok in ("sqlite", "database required", "must use database")):
        issues.append("Contradiction: no database and database required.")
    return issues


def local_import_findings(workspace: DevWorkspace, files: list[str]) -> list[str]:
    """Report unresolved relative/local imports. Does not import modules."""
    modules = set()
    for rel in files:
        if rel.endswith(".py"):
            stem = rel[:-3].replace("/", ".")
            modules.add(stem.split(".")[-1])
            modules.add(stem)
    findings: list[str] = []
    for rel in files:
        if not rel.endswith(".py"):
            continue
        try:
            text = workspace.read_text(rel)
        except WorkspaceError:
            findings.append(f"missing:{rel}")
            continue
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            findings.append(f"syntax:{rel}:{exc.lineno}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                name = node.module.split(".")[0]
                if name not in modules and not name.startswith("_"):
                    # stdlib-ish short names are not flagged if common
                    if name not in {"os", "sys", "json", "pathlib", "typing", "re"}:
                        findings.append(f"unresolved_import:{rel}:{node.module}")
    return findings


def coverage_gaps(spec: Optional[RequirementSpec], traced_ids: set[str]) -> list[str]:
    if spec is None:
        return ["missing_spec"]
    missing = [
        c.criterion_id
        for c in spec.acceptance_criteria
        if c.required and c.criterion_id not in traced_ids
    ]
    return [f"untraced_criterion:{cid}" for cid in missing]
