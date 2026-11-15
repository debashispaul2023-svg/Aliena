"""Static lint and test-plan validation. Does not import or execute generated code."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

DANGEROUS_IMPORTS = {"os", "subprocess", "socket", "ctypes", "shutil"}


@dataclass
class LintFinding:
    path: str
    code: str
    message: str
    line: int | None = None


@dataclass
class LintReport:
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.code in {"syntax_error", "dangerous_import"} for f in self.findings)


def lint_source(path: str, source: str) -> list[LintFinding]:
    findings: list[LintFinding] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        findings.append(LintFinding(path, "syntax_error", str(exc), exc.lineno))
        return findings
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in DANGEROUS_IMPORTS:
                    findings.append(LintFinding(path, "dangerous_import", alias.name, node.lineno))
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in DANGEROUS_IMPORTS:
                findings.append(LintFinding(path, "dangerous_import", node.module, node.lineno))
    return findings


def lint_files(files: list[tuple[str, str]]) -> LintReport:
    report = LintReport()
    for path, source in files:
        report.findings.extend(lint_source(path, source))
    return report


def validate_test_plan(plan: dict, workspace: Path) -> list[str]:
    """Validate a test plan without importing or executing tests."""
    errors = []
    tests = plan.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("tests must be a non-empty list")
        return errors
    for item in tests:
        if not isinstance(item, str) or not item.endswith(".py"):
            errors.append(f"invalid test path: {item!r}")
            continue
        target = (workspace / item).resolve()
        try:
            target.relative_to(workspace.resolve())
        except ValueError:
            errors.append(f"path escapes workspace: {item}")
            continue
        if not target.is_file():
            errors.append(f"missing test file: {item}")
    return errors
