"""C7 testing engine: project-level STATIC checks, test generation, and honest test reporting.

No generated code is executed. Runtime-class test categories are reported as BLOCKED (never as passed)
together with the exact commands a user could run in their own isolated environment."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Optional

from jarvis.core.redaction import redact_secrets
from jarvis.creator.analysis import analyze_dependencies
from jarvis.creator.audit import AuditLogger
from jarvis.creator.security_gate import SecurityGate
from jarvis.creator.validators import validate_content
from jarvis.creator.workspace_manager import CreatorWorkspaceError, CreatorWorkspaceManager

CHECKS = ("syntax", "dependencies", "references", "imports", "structure", "integrity", "secrets")
BLOCKED_CATEGORIES = ("unit_tests", "integration_tests", "build_checks", "runtime_tests", "browser_tests")
BLOCK_REASON = "generated-code execution is BLOCKED (Phase 6F: no verified OS-level isolation)"
_TEXT_EXT = (".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".html", ".css", ".json", ".toml", ".yaml", ".yml",
             ".md", ".sql", ".svg", ".txt", ".cfg", ".ini", ".example", ".gitignore")
_JS_REL = [re.compile(r"""from\s+['"](\.{1,2}/[^'"]+)['"]"""), re.compile(r"""import\s+['"](\.{1,2}/[^'"]+)['"]"""),
           re.compile(r"""require\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""")]


@dataclass
class Finding:
    check: str
    severity: str  # error | warning
    path: str
    message: str
    data: dict = field(default_factory=dict)

    @property
    def fid(self) -> str:
        return hashlib.sha256(f"{self.check}|{self.path}|{self.message}".encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {"id": self.fid, "check": self.check, "severity": self.severity, "path": self.path,
                "message": self.message, "data": self.data}


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.refs.append(v)

    handle_startendtag = handle_starttag


def _is_text(path: str) -> bool:
    low = path.lower()
    return low.endswith(_TEXT_EXT) or "." not in posixpath.basename(low)


class ProjectChecker:
    def __init__(self, ws: CreatorWorkspaceManager) -> None:
        self.ws = ws

    def _load(self, pid: str) -> dict[str, str]:
        files = {}
        for key in self.ws.manifest(pid):
            if _is_text(key):
                try:
                    files[key] = self.ws.read_file(pid, key).decode("utf-8")
                except (CreatorWorkspaceError, UnicodeDecodeError):
                    files[key] = ""
        return files

    def check(self, pid: str) -> dict[str, Any]:
        tracked = set(self.ws.manifest(pid))
        files = self._load(pid)
        findings: list[Finding] = []
        # syntax
        unvalidated = []
        for path, text in sorted(files.items()):
            v = validate_content(path, text)
            if not v.ok:
                findings.append(Finding("syntax", "error", path, "; ".join(v.errors)[:200], {"level": v.level}))
            if not v.validated:
                unvalidated.append(path)
        # dependencies
        dep = analyze_dependencies(files)
        for mod in dep["python"]["undeclared"]:
            findings.append(Finding("dependencies", "error", "requirements.txt", f"python import '{mod}' is not declared",
                                    {"language": "python", "name": mod}))
        for mod in dep["javascript"]["undeclared"]:
            findings.append(Finding("dependencies", "error", "package.json", f"javascript import '{mod}' is not declared",
                                    {"language": "javascript", "name": mod}))
        # references (html) and imports (js)
        for path, text in sorted(files.items()):
            base = posixpath.dirname(path)
            if path.endswith((".html", ".htm")):
                p = _Refs()
                try:
                    p.feed(text)
                except Exception:
                    continue
                for ref in p.refs:
                    if re.match(r"^(#|mailto:|tel:|data:|javascript:)", ref):
                        if ref.lower().startswith("javascript:"):
                            findings.append(Finding("references", "error", path, "javascript: URL is not allowed"))
                        continue
                    if re.match(r"^(https?:)?//", ref):
                        findings.append(Finding("references", "warning", path, f"external resource: {ref[:80]}"))
                        continue
                    clean = ref.split("#")[0].split("?")[0]
                    target = posixpath.normpath(posixpath.join(base, clean)) if not clean.startswith("/") else clean.lstrip("/")
                    if target.startswith("..") or (target not in tracked and not any(t.startswith(target.rstrip("/") + "/") for t in tracked)):
                        findings.append(Finding("references", "error", path, f"missing local reference: {ref}",
                                                {"ref": ref, "resolved": target}))
            if path.endswith((".js", ".jsx", ".mjs", ".ts", ".tsx")):
                for rx in _JS_REL:
                    for spec in rx.findall(text):
                        target = posixpath.normpath(posixpath.join(base, spec))
                        cands = [target] + [target + e for e in (".js", ".jsx", ".mjs", ".json", ".ts", ".tsx")] + \
                                [target + "/index" + e for e in (".js", ".jsx", ".ts", ".tsx")]
                        if not any(c in tracked for c in cands):
                            findings.append(Finding("imports", "error", path, f"unresolved relative import: {spec}", {"spec": spec}))
        # structure
        if not any(t.lower().startswith("readme") for t in tracked):
            findings.append(Finding("structure", "error", "README.md", "README is missing"))
        if not any(re.search(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*|\.test\.[jt]sx?$", t) for t in tracked):
            findings.append(Finding("structure", "warning", "tests/", "project has no tests"))
        # integrity
        integ = self.ws.verify_integrity(pid)
        for p in integ["modified"]:
            findings.append(Finding("integrity", "error", p, "file differs from manifest hash"))
        for p in integ["missing"]:
            findings.append(Finding("integrity", "error", p, "tracked file is missing"))
        # secrets
        for path, text in sorted(files.items()):
            if text and redact_secrets(text) != text:
                findings.append(Finding("secrets", "error", path, "possible secret/credential pattern"))
        by_check = {c: {"errors": 0, "warnings": 0} for c in CHECKS}
        for f in findings:
            by_check[f.check]["errors" if f.severity == "error" else "warnings"] += 1
        return {"project_id": pid, "files_checked": len(files), "unvalidated_files": sorted(unvalidated),
                "findings": [f.to_dict() for f in findings], "by_check": by_check,
                "passed": all(c["errors"] == 0 for c in by_check.values())}


def prepared_commands(tracked: set[str], package_json: Optional[dict] = None) -> list[dict]:
    """Commands a user could run in their OWN isolated environment. Aliena never runs them."""
    cmds = []
    py_tests = [t for t in tracked if t.startswith("tests/") and t.endswith(".py")]
    if "tests/conftest.py" in tracked:
        cmds.append({"category": "unit_tests", "command": ["python", "-m", "pytest"], "note": "after installing requirements.txt"})
    elif py_tests:
        cmds.append({"category": "unit_tests", "command": ["python", "-m", "unittest", "discover", "-s", "tests"],
                     "env_hint": "PYTHONPATH=src" if any(t.startswith("src/") for t in tracked) else "", "note": "stdlib unittest"})
    scripts = (package_json or {}).get("scripts", {}) if isinstance(package_json, dict) else {}
    if "test" in scripts:
        cmds.append({"category": "unit_tests", "command": ["npm", "test"], "note": "after npm install"})
    if "build" in scripts:
        cmds.append({"category": "build_checks", "command": ["npm", "run", "build"], "note": "after npm install"})
    return cmds


class TestManager:
    __test__ = False  # not a pytest test class

    def __init__(self, ws: CreatorWorkspaceManager, gate: SecurityGate, audit: Optional[AuditLogger] = None) -> None:
        self.ws, self.gate, self.audit = ws, gate, audit or ws.audit
        self.checker = ProjectChecker(ws)

    def run(self, pid: str, actor: str = "testing") -> dict[str, Any]:
        d = self.gate.check(pid, actor, "run_static_checks")
        if not d.allowed:
            raise CreatorWorkspaceError(d.reason)
        # any attempt to execute is denied and audited here as proof the boundary holds
        self.gate.check(pid, actor, "execute_code")
        static = self.checker.check(pid)
        tracked = set(self.ws.manifest(pid))
        cats: dict[str, Any] = {}
        for name in CHECKS:
            c = static["by_check"][name]
            cats[name] = {"status": "passed" if c["errors"] == 0 else "failed", **c, "executed_code": False}
        pkg = None
        if "package.json" in tracked:
            try:
                pkg = json.loads(self.ws.read_file(pid, "package.json").decode("utf-8"))
            except (ValueError, CreatorWorkspaceError):
                pkg = None
        cmds = prepared_commands(tracked, pkg)
        for name in BLOCKED_CATEGORIES:
            cats[name] = {"status": "blocked", "reason": BLOCK_REASON, "exit_code": None, "executed_code": False,
                          "prepared_commands": [c for c in cmds if c["category"] == name]}
        failed = [n for n in CHECKS if cats[n]["status"] == "failed"]
        if failed:
            completion = {"complete": False, "status": "failed_static_checks", "reasons": [f"failed: {n}" for n in failed]}
        else:
            completion = {"complete": True, "status": "static_verified_runtime_unverified",
                          "reasons": ["static checks passed", "runtime/unit/integration/build/browser tests NOT run: " + BLOCK_REASON]}
        report = {"project_id": pid, "created_at": datetime.now(timezone.utc).isoformat(), "categories": cats,
                  "findings": static["findings"], "files_checked": static["files_checked"],
                  "unvalidated_files": static["unvalidated_files"], "completion": completion,
                  "commands_executed": [], "ai_generated": False}
        seq = len(self.ws.list_control_records(pid, "reports")) + 1
        self.ws.save_control_record(pid, "reports", f"report_{seq:04d}", report)
        self.audit.record(pid, actor, "test_report", "ok" if completion["complete"] else "failed",
                          f"{completion['status']} errors={sum(1 for f in static['findings'] if f['severity'] == 'error')}")
        return report


class TestGenerator:
    """Adds a smoke test file when a Python project lacks one. The file is written, never run."""
    __test__ = False

    def __init__(self, ws: CreatorWorkspaceManager, gate: SecurityGate) -> None:
        self.ws, self.gate = ws, gate

    def generate(self, pid: str, actor: str = "testing") -> list[str]:
        if not self.gate.check(pid, actor, "generate_tests").allowed:
            return []
        tracked = set(self.ws.manifest(pid))
        pys = sorted(t for t in tracked if t.endswith(".py") and not t.startswith(("tests/", "test_")) and "/tests/" not in t
                     and not t.endswith("__init__.py") and not t.endswith("conftest.py"))
        target = "tests/test_generated_smoke.py"
        if not pys or target in tracked:
            return []
        body = f'''"""Generated smoke test: every module compiles and the README exists. Run by you; never run by Aliena."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = {pys!r}


class TestSmoke(unittest.TestCase):
    def test_modules_parse(self):
        for rel in MODULES:
            source = (ROOT / rel).read_text(encoding="utf-8")
            ast.parse(source, filename=rel)

    def test_readme_exists(self):
        self.assertTrue(any(p.name.lower().startswith("readme") for p in ROOT.iterdir()))


if __name__ == "__main__":
    unittest.main()
'''
        self.ws.write_file(pid, target, body, actor=actor)
        return [target]
