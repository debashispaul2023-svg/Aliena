"""C7 tests: static project checks, test manager reporting, test generation, bounded debugging."""

import ast
import json
import unittest
from pathlib import Path

from jarvis.creator import testing_engine as te
from jarvis.creator.debug_manager import MAX_ROUNDS, DebugManager, strip_trailing_commas
from jarvis.creator.testing_engine import ProjectChecker, TestGenerator, TestManager
from jarvis.creator.workspace_manager import ApprovalRequired, CreatorWorkspaceError, PathViolation
from jarvis.tests.creator_testkit import CreatorBase, ok
from jarvis.tests.test_creator_c4 import SPEC as SITE
from jarvis.tests.test_creator_c5_c6 import API, GAME, MOBILE, PY

ALL = {"website": SITE, "fastapi_service": API, "python_software": PY, "mobile_app": MOBILE, "game_collector": GAME}


class C7Base(CreatorBase):
    def setUp(self):
        super().setUp()
        self.checker = ProjectChecker(self.ws)
        self.tm = TestManager(self.ws, self.gate, self.audit)
        self.dbg = DebugManager(self.ws, self.audit)

    def put(self, rel, content):
        self.ws.write_file(self.pid, rel, content)

    def errors(self, check=None):
        r = self.checker.check(self.pid)
        return [f for f in r["findings"] if f["severity"] == "error" and check in (None, f["check"])]


class TestChecker(C7Base):
    def test_every_composer_output_passes_static_checks(self):
        for cid, spec in ALL.items():
            pid = self.ws.create_project("p")
            self.gen.compose(pid, cid, spec)
            r = self.checker.check(pid)
            self.assertTrue(r["passed"], (cid, [f for f in r["findings"] if f["severity"] == "error"]))

    def test_every_template_output_passes_static_checks(self):
        for t in self.gen.registry.list():
            pid = self.ws.create_project("p")
            self.gen.generate(pid, t["template_id"], {"project_name": "Demo Site"})
            r = self.checker.check(pid)
            self.assertTrue(r["passed"], (t["template_id"], [f for f in r["findings"] if f["severity"] == "error"]))

    def test_detects_defects(self):
        self.put("README.md", "# x\n")
        self.put("bad.py", "def (:\n")
        self.put("dep.py", "import requests\n")
        self.put("page.html", '<html><body><link href="css/missing.css"><a href="javascript:alert(1)">x</a>'
                              '<script src="https://cdn.example.com/x.js"></script></body></html>')
        self.put("web/a.js", "import x from './nope';\nimport y from './ok';\n")
        self.put("web/ok.js", "export default 1;\n")
        self.put("cfg.json", '{"a": 1,}')
        self.put("keys.txt", "token = sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n")
        r = self.checker.check(self.pid)
        by = {(f["check"], f["path"]) for f in r["findings"] if f["severity"] == "error"}
        self.assertIn(("syntax", "bad.py"), by)
        self.assertIn(("syntax", "cfg.json"), by)
        self.assertIn(("dependencies", "requirements.txt"), by)
        self.assertIn(("references", "page.html"), by)
        self.assertIn(("imports", "web/a.js"), by)
        self.assertIn(("secrets", "keys.txt"), by)
        msgs = " ".join(f["message"] for f in r["findings"])
        self.assertIn("javascript: URL", msgs)
        self.assertIn("unresolved relative import: ./nope", msgs)
        self.assertNotIn("./ok", msgs)
        warn = [f for f in r["findings"] if f["severity"] == "warning"]
        self.assertTrue(any("external resource" in f["message"] for f in warn))
        self.assertFalse(r["passed"])

    def test_structure_and_integrity(self):
        self.put("a.txt", "x")
        self.assertTrue(any(f["check"] == "structure" and "README" in f["message"] for f in self.errors()))
        (self.pdir() / "a.txt").write_text("changed")
        self.assertTrue(self.errors("integrity"))
        (self.pdir() / "a.txt").unlink()
        self.assertTrue(any("missing" in f["message"] for f in self.errors("integrity")))

    def test_resolves_relative_refs_and_ignores_anchors(self):
        self.put("README.md", "x")
        self.put("site/index.html", '<a href="#top">t</a><a href="../up.html">u</a><img src="img/a.svg">')
        self.put("up.html", "<p>x</p>")
        self.put("site/img/a.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertEqual(self.errors("references"), [])

    def test_ref_escaping_workspace_is_flagged(self):
        self.put("README.md", "x")
        self.put("p.html", '<img src="../../etc/passwd">')
        self.assertTrue(self.errors("references"))

    def test_checks_never_execute_code(self):
        marker = Path(self._tmp.name) / "marker"
        self.put("README.md", "x")
        self.put("evil.py", f"open({str(marker)!r}, 'w').write('x')\n")
        self.checker.check(self.pid)
        self.tm.run(self.pid)
        self.assertFalse(marker.exists())


class TestManagerReport(C7Base):
    def test_report_is_honest_about_blocked_execution(self):
        self.gen.compose(self.pid, "python_software", PY)
        rep = self.tm.run(self.pid)
        cats = rep["categories"]
        for name in te.CHECKS:
            self.assertEqual(cats[name]["status"], "passed", name)
            self.assertFalse(cats[name]["executed_code"])
        for name in te.BLOCKED_CATEGORIES:
            self.assertEqual(cats[name]["status"], "blocked", name)
            self.assertIsNone(cats[name]["exit_code"])
            self.assertIn("BLOCKED", cats[name]["reason"])
        self.assertEqual(rep["commands_executed"], [])
        self.assertEqual(rep["completion"], {"complete": True, "status": "static_verified_runtime_unverified",
                                             "reasons": rep["completion"]["reasons"]})
        self.assertTrue(any("NOT run" in r for r in rep["completion"]["reasons"]))
        unit = cats["unit_tests"]["prepared_commands"]
        self.assertEqual(unit[0]["command"][:3], ["python", "-m", "unittest"])
        self.assertEqual(unit[0]["env_hint"], "PYTHONPATH=src")

    def test_prepared_commands_per_project_kind(self):
        self.gen.compose(self.pid, "fastapi_service", API)
        self.assertEqual(self.tm.run(self.pid)["categories"]["unit_tests"]["prepared_commands"][0]["command"], ["python", "-m", "pytest"])
        p2 = self.ws.create_project("m")
        self.gen.compose(p2, "mobile_app", MOBILE)
        rep = self.tm.run(p2)
        self.assertEqual(rep["categories"]["unit_tests"]["prepared_commands"][0]["command"], ["npm", "test"])
        self.assertEqual(rep["categories"]["build_checks"]["prepared_commands"], [])  # no build script => none claimed

    def test_failing_static_check_blocks_completion(self):
        self.put("README.md", "x")
        self.put("bad.py", "def (:\n")
        rep = self.tm.run(self.pid)
        self.assertFalse(rep["completion"]["complete"])
        self.assertEqual(rep["completion"]["status"], "failed_static_checks")
        self.assertEqual(rep["categories"]["syntax"]["status"], "failed")

    def test_report_persisted_and_audited_and_execution_denied(self):
        self.gen.compose(self.pid, "python_software", PY)
        self.tm.run(self.pid)
        self.tm.run(self.pid)
        self.assertEqual(self.ws.list_control_records(self.pid, "reports"), ["report_0001", "report_0002"])
        stored = self.ws.load_control_record(self.pid, "reports", "report_0002")
        self.assertFalse(stored["ai_generated"])
        acts = [(r["action"], r["outcome"]) for r in self.audit.records(self.pid)]
        self.assertIn(("execute_code", "denied"), acts)
        self.assertIn(("test_report", "ok"), acts)
        self.assertTrue(self.audit.verify_chain())


class TestTestGenerator(C7Base):
    def test_generates_smoke_test_once(self):
        self.put("README.md", "x")
        self.put("src/pkg/core.py", "x = 1\n")
        self.put("src/pkg/__init__.py", "")
        tg = TestGenerator(self.ws, self.gate)
        self.assertEqual(tg.generate(self.pid), ["tests/test_generated_smoke.py"])
        tree = ast.parse(self.text("tests/test_generated_smoke.py"))
        self.assertIn("src/pkg/core.py", self.text("tests/test_generated_smoke.py"))
        self.assertNotIn("__init__", self.text("tests/test_generated_smoke.py"))
        self.assertTrue(any(isinstance(n, ast.ClassDef) for n in tree.body))
        self.assertEqual(tg.generate(self.pid), [])  # idempotent, no overwrite
        self.assertTrue(self.checker.check(self.pid)["passed"])

    def test_nothing_for_non_python_projects(self):
        self.put("index.html", "<p>x</p>")
        self.assertEqual(TestGenerator(self.ws, self.gate).generate(self.pid), [])


class TestStripCommas(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(json.loads(strip_trailing_commas('{"a": [1, 2,], "b": {"c": 1,},}')), {"a": [1, 2], "b": {"c": 1}})
        self.assertEqual(json.loads(strip_trailing_commas('{"s": "keep,} this", }')), {"s": "keep,} this"})
        self.assertIsNone(strip_trailing_commas("{bad json,}"))
        self.assertEqual(strip_trailing_commas('{"a": 1}'), '{"a": 1}')


class TestCorrectGenerated(C7Base):
    def test_only_tracked_unmodified_generated_files(self):
        self.put("a.txt", "one")
        self.ws.correct_generated_file(self.pid, "a.txt", "two")
        self.assertEqual(self.text("a.txt"), "two")
        self.assertTrue(self.ws.manifest(self.pid)["a.txt"]["corrected"])
        self.assertTrue(self.ws.verify_integrity(self.pid)["ok"])
        (self.pdir() / "user.txt").write_text("mine")
        with self.assertRaises(ApprovalRequired):
            self.ws.correct_generated_file(self.pid, "user.txt", "x")
        (self.pdir() / "a.txt").write_text("user edit")
        with self.assertRaises(ApprovalRequired):
            self.ws.correct_generated_file(self.pid, "a.txt", "x")
        self.assertEqual(self.text("a.txt"), "user edit")
        with self.assertRaises(PathViolation):
            self.ws.correct_generated_file(self.pid, "../x.txt", "x")
        self.assertEqual(len(list((self.pdir() / ".creator" / "backups").rglob("a.txt"))), 1)


class TestDebugManager(C7Base):
    def setup_fixable(self):
        self.gen.compose(self.pid, "fastapi_service", API)
        self.put("page.html", '<html><body><link rel="stylesheet" href="css/missing.css"><script src="js/missing.js"></script></body></html>')
        self.put("data.json", '{"a": [1, 2,],}')
        self.put("extra.py", "import requests\nimport numpy\n")

    def test_fixes_safe_defects_and_verifies(self):
        self.setup_fixable()
        run = self.dbg.run(self.pid)
        self.assertGreater(run["errors_before"], 0)
        self.assertTrue(run["resolved"], run["remaining"])
        self.assertEqual(run["errors_after"], 0)
        self.assertLessEqual(len(run["rounds"]), MAX_ROUNDS)
        self.assertTrue(run["regression"]["integrity_ok"])
        self.assertEqual(run["commands_executed"], [])
        self.assertIsNotNone(run["checkpoint"])
        self.assertIn("generated stub", self.text("css/missing.css"))
        self.assertTrue(self.text("js/missing.js").startswith("// generated stub"))
        self.assertEqual(json.loads(self.text("data.json")), {"a": [1, 2]})
        req = self.text("requirements.txt").splitlines()
        self.assertIn("requests", req)
        self.assertIn("numpy", req)
        self.assertEqual(req.count("pydantic>=2.0"), 1)
        self.assertTrue(self.checker.check(self.pid)["passed"])
        self.assertTrue(self.ws.list_control_records(self.pid, "debug"))

    def test_unfixable_defects_become_proposals_not_loops(self):
        self.gen.compose(self.pid, "python_software", PY)
        self.put("bad.py", "def (:\n")
        self.put("web.js", "import left from 'left-pad';\n")
        self.put("keys.txt", "k = sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n")
        before = {p: self.text(p) for p in ("bad.py", "web.js", "keys.txt")}
        run = self.dbg.run(self.pid)
        self.assertFalse(run["resolved"])
        self.assertLessEqual(len(run["rounds"]), MAX_ROUNDS)
        self.assertEqual(run["stopped"], "no applicable automatic fixes")
        props = {(p["check"], p["path"]) for p in run["rounds"][0]["proposals"]}
        self.assertTrue({("syntax", "bad.py"), ("secrets", "keys.txt"), ("dependencies", "package.json")} <= props)
        self.assertEqual({p: self.text(p) for p in before}, before)  # never touched

    def test_user_modified_file_not_auto_corrected(self):
        self.put("README.md", "x")
        self.put("data.json", '{"a": 1}')
        (self.pdir() / "data.json").write_text('{"a": 1,}')  # user edit outside Creator
        run = self.dbg.run(self.pid)
        self.assertFalse(run["resolved"])
        self.assertEqual(self.text("data.json"), '{"a": 1,}')
        skipped = [s for r in run["rounds"] for s in r["skipped"]]
        self.assertTrue(any("modified outside Creator" in s.get("error", "") for s in skipped))

    def test_clean_project_is_a_noop(self):
        self.gen.compose(self.pid, "python_software", PY)
        cps = self.ws.list_checkpoints(self.pid)
        run = self.dbg.run(self.pid)
        self.assertEqual((run["errors_before"], run["rounds"], run["checkpoint"], run["resolved"]), (0, [], None, True))
        self.assertEqual(self.ws.list_checkpoints(self.pid), cps)  # debug took no checkpoint

    def test_round_bound_is_enforced(self):
        self.setup_fixable()
        run = self.dbg.run(self.pid, max_rounds=999)
        self.assertLessEqual(len(run["rounds"]), MAX_ROUNDS)
        run0 = self.dbg.run(self.pid, max_rounds=-5)
        self.assertGreaterEqual(run0["errors_before"], 0)

    def test_correction_is_undoable_via_checkpoint(self):
        self.setup_fixable()
        run = self.dbg.run(self.pid)
        self.ws.rollback(self.pid, run["checkpoint"], approval=ok("delete_file"))
        self.assertNotIn("css/missing.css", self.ws.manifest(self.pid))
        self.assertEqual(self.text("data.json"), '{"a": [1, 2,],}')

    def test_audit_trail(self):
        self.setup_fixable()
        self.dbg.run(self.pid)
        acts = {(r["action"], r["outcome"]) for r in self.audit.records(self.pid)}
        self.assertIn(("debug_run", "resolved"), acts)
        self.assertIn(("correct_generated_file", "allowed"), acts)
        self.assertTrue(self.audit.verify_chain())


class TestNoExecutionPrimitives(unittest.TestCase):
    def test_sources(self):
        banned = ("subprocess", "os.system", "os.popen", "eval(", "exec(", "shell=True", "import socket",
                  "importlib", "__import__", "runpy")
        import re
        for name in ("testing_engine.py", "debug_manager.py"):
            src = (Path(te.__file__).parent / name).read_text()
            for b in banned:
                self.assertNotIn(b, src, f"{b} in {name}")
            self.assertIsNone(re.search(r"(?<![\w.])compile\(", src), f"builtin compile( in {name}")


if __name__ == "__main__":
    unittest.main()
