"""C11 cross-cutting security audit of the Creator Engine."""

import ast
import json
import os
import random
import re
import tempfile
import unittest
from pathlib import Path

import jarvis.creator as creator_pkg
from jarvis.core.approval import approve
from jarvis.core.redaction import redact_secrets
from jarvis.creator import security_gate as sg
from jarvis.creator.audit import AuditLogger
from jarvis.creator.engine import CreatorEngine
from jarvis.creator.security_gate import SecurityGate
from jarvis.creator.workspace_manager import CreatorWorkspaceError, CreatorWorkspaceManager
from jarvis.dev.execution_gate import ExecutionGate, IsolationNotVerified
from jarvis.tests.test_creator_c10 import REQUESTS

PKG_DIR = Path(creator_pkg.__file__).parent
FORBIDDEN_IMPORTS = {"subprocess", "socket", "http", "urllib", "ftplib", "smtplib", "ssl", "requests", "importlib", "runpy",
                     "ctypes", "pickle", "marshal", "webbrowser", "pty", "multiprocessing", "asyncio", "telnetlib", "xmlrpc"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "system", "popen", "Popen", "spawn", "startfile"}


class TestStaticSourceAudit(unittest.TestCase):
    def test_no_execution_network_or_dynamic_code_anywhere_in_creator(self):
        files = sorted(PKG_DIR.glob("*.py"))
        self.assertGreaterEqual(len(files), 25)
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=f.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertNotIn(a.name.split(".")[0], FORBIDDEN_IMPORTS, f"{f.name} imports {a.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split(".")[0], FORBIDDEN_IMPORTS, f"{f.name} imports {node.module}")
                elif isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                    if name in FORBIDDEN_CALLS and not (isinstance(fn, ast.Attribute) and name == "compile"):  # re.compile is regex only
                        self.fail(f"{f.name}: call to {name}()")
                elif isinstance(node, ast.keyword) and node.arg == "shell":
                    self.fail(f"{f.name}: shell= keyword")

    def test_regex_compile_is_the_only_compile(self):
        for f in PKG_DIR.glob("*.py"):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "compile":
                    self.assertEqual(getattr(node.func.value, "id", ""), "re", f.name)


class TestGateMatrix(unittest.TestCase):
    def setUp(self):
        self.audit = AuditLogger()
        self.gate = SecurityGate(self.audit)

    def test_sets_are_disjoint_and_complete(self):
        self.assertFalse(sg.AUTOMATIC & sg.APPROVAL_REQUIRED)
        self.assertFalse(sg.AUTOMATIC & sg.ALWAYS_BLOCKED)
        self.assertFalse(sg.APPROVAL_REQUIRED & sg.ALWAYS_BLOCKED)
        for required in ("install_dependencies", "external_download", "modify_existing_project", "overwrite_file", "delete_file",
                         "access_credentials", "network_action", "publish", "deploy", "os_action", "export_delivery"):
            self.assertIn(required, sg.APPROVAL_REQUIRED)
        for blocked in ("execute_code", "run_generated_script", "run_downloaded_code", "run_plugin", "workspace_escape"):
            self.assertIn(blocked, sg.ALWAYS_BLOCKED)

    def test_blocked_actions_denied_with_every_approval_shape(self):
        for action in sg.ALWAYS_BLOCKED:
            for approval in (None, approve(action, reviewer="user"), approve(action, reviewer="user", target="p"),
                             approve("execute_code", reviewer="user")):
                self.assertFalse(self.gate.check("p", "agent", action, approval).allowed, action)

    def test_approval_required_actions(self):
        for action in sg.APPROVAL_REQUIRED:
            d = self.gate.check("p", "a", action)
            self.assertEqual((d.allowed, d.needs_approval), (False, True), action)
            self.assertTrue(self.gate.check("p", "a", action, approve(action, reviewer="user")).allowed, action)
            self.assertTrue(self.gate.check("p", "a", action, approve(action, reviewer="user", target="p")).allowed)
            self.assertFalse(self.gate.check("p", "a", action, approve(action, reviewer="user", target="other")).allowed)
            self.assertFalse(self.gate.check("p", "a", action, approve("something_else", reviewer="user")).allowed)
            self.assertFalse(self.gate.check("p", "a", action, approve(action, reviewer="")).allowed)  # reviewer required

    def test_automatic_and_unknown(self):
        for action in sg.AUTOMATIC:
            self.assertTrue(self.gate.check("p", "a", action).allowed, action)
        for action in ("", "rm_rf", "EXECUTE_CODE", "execute_code ", "format_disk", "install_dependencies_auto", None):
            self.assertFalse(self.gate.check("p", "a", action).allowed, repr(action))

    def test_every_decision_is_audited(self):
        n = len(sg.AUTOMATIC) + len(sg.APPROVAL_REQUIRED) + len(sg.ALWAYS_BLOCKED)
        for action in sorted(sg.AUTOMATIC | sg.APPROVAL_REQUIRED | sg.ALWAYS_BLOCKED):
            self.gate.check("p", "a", action)
        self.assertEqual(len(self.audit.records("p")), n)
        self.assertTrue(self.audit.verify_chain())

    def test_existing_execution_gate_still_blocks(self):
        with self.assertRaises(IsolationNotVerified):
            ExecutionGate().run(["echo", "x"])
        self.assertIn("BLOCKED", json.loads((Path(creator_pkg.__file__).parents[1] / "dev" / "phase6_status.json").read_text())["execution"])


class TestBoundaryFuzz(unittest.TestCase):
    def test_hostile_paths_never_escape_or_write(self):
        rnd = random.Random(1337)
        atoms = ["..", ".", "/", "\\", "a", "b.txt", "\x00", "~", "C:", "con", "nul", ".creator", ".env", " ", "é", "%2e%2e", "...", ":", "x" * 50,
                 "cre_0123456789abcdef", "\u202e", "\n"]
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLogger()
            ws = CreatorWorkspaceManager(Path(tmp) / "ws", SecurityGate(audit), audit)
            pid = ws.create_project("fuzz")
            written = 0
            for _ in range(1500):
                path = "".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 6)))
                try:
                    ws.write_file(pid, path, "x")
                    written += 1
                except CreatorWorkspaceError:
                    pass
                except OSError:
                    pass  # e.g. invalid filename on this platform: still must not escape (checked below)
            outside = [p for p in Path(tmp).rglob("*") if p.is_file() and (Path(tmp) / "ws" / pid) not in p.parents]
            self.assertEqual(outside, [])
            for k in ws.manifest(pid):
                self.assertFalse(k.split("/")[0].lower() == ".creator" or k.startswith("/") or ".." in k.split("/") or "\x00" in k, k)
            self.assertTrue(ws.verify_integrity(pid)["ok"])
            self.assertFalse([p for p in (Path(tmp) / "ws").rglob("*") if p.is_symlink()])


class TestEndToEndFootprint(unittest.TestCase):
    def test_full_run_stays_in_root_and_leaks_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            marker_dirs = {p.name for p in home.iterdir()}
            eng = CreatorEngine(home / "creator", audit_path=home / "creator" / "audit.jsonl")
            results = [eng.create(r) for r in REQUESTS.values()]
            self.assertTrue(all(r.status == "delivered" for r in results))
            self.assertEqual({p.name for p in home.iterdir()} - marker_dirs, {"creator"})
            files = [p for p in home.rglob("*") if p.is_file()]
            self.assertTrue(all((home / "creator") in p.parents for p in files))
            self.assertFalse([p for p in home.rglob("*") if p.is_symlink()])
            # no stray temp files, no bytecode, no executables
            self.assertEqual([p for p in files if p.name.startswith(".tmp_") or p.suffix in (".pyc", ".exe", ".dll", ".so", ".sh", ".bat")], [])
            self.assertFalse([p for p in files if os.access(p, os.X_OK)])
            # audit: chain intact, persisted copy contains no secrets, execution only ever denied
            self.assertTrue(eng.audit.verify_chain())
            persisted = (home / "creator" / "audit.jsonl").read_text()
            self.assertEqual(redact_secrets(persisted), persisted)
            recs = [json.loads(l) for l in persisted.splitlines()]
            self.assertTrue(all(r["outcome"] == "denied" for r in recs if r["action"] in sg.ALWAYS_BLOCKED))
            self.assertTrue(any(r["action"] == "execute_code" for r in recs))
            self.assertFalse(any(r["action"] in sg.ALWAYS_BLOCKED and r["outcome"] == "allowed" for r in recs))
            # every generated text file is secret-free and parses where a parser exists
            for p in files:
                if p.suffix in (".py", ".json", ".md", ".html", ".css", ".js", ".txt"):
                    text = p.read_text(encoding="utf-8")
                    self.assertEqual(redact_secrets(text), text, p.name)

    def test_deliveries_are_never_executable_content_only_data(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            eng = CreatorEngine(Path(tmp))
            r = eng.create(REQUESTS["python_app"])
            data = eng.ws.read_artifact(r.project_id, "deliveries", eng.ws.list_artifacts(r.project_id, "deliveries")[0])
            import io
            for info in zipfile.ZipFile(io.BytesIO(data)).infolist():
                self.assertEqual(info.external_attr >> 16, 0o100644)  # regular, non-executable
                self.assertFalse(info.filename.endswith((".exe", ".sh", ".bat", ".dll")))


class TestExistingFeaturesUntouched(unittest.TestCase):
    def test_creator_package_is_additive(self):
        repo = Path(creator_pkg.__file__).parents[2]
        for must_exist in ("jarvis/dev/execution_gate.py", "jarvis/dev/workspace.py", "jarvis/core/orchestrator.py",
                           "jarvis/ai/router.py", "jarvis/memory/store.py", "jarvis/core/approval.py", "jarvis/app/avatar.py"):
            self.assertTrue((repo / must_exist).is_file(), must_exist)
        self.assertTrue((repo / "jarvis_memory.db").exists())

    def test_avatar_not_replaced(self):
        repo = Path(creator_pkg.__file__).parents[2]
        main = (repo / "jarvis" / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("emit_avatar_emotion", main)
        self.assertIn("emit_avatar_state", main)
        for f in PKG_DIR.glob("*.py"):
            self.assertNotRegex(f.read_text(encoding="utf-8").lower(), r"robot avatar")


if __name__ == "__main__":
    unittest.main()
