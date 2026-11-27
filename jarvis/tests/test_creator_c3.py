"""Creator Engine C3 tests: code generation, validation, collisions, atomicity, security, reproducibility."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core.approval import ApprovalDecision
from jarvis.creator import (AuditLogger, CodeGenerationManager, CreatorWorkspaceManager, SecurityGate,
                            TemplateRegistry, default_registry)
from jarvis.creator import codegen_manager as cg
from jarvis.creator.analysis import analyze_dependencies
from jarvis.creator.builtin_templates import BUILTIN
from jarvis.creator.codegen_manager import GenerationError, derive_variables
from jarvis.creator.templates import Template, TemplateError
from jarvis.creator.validators import validate_content
from jarvis.creator.workspace_manager import (ApprovalRequired, CollisionError, CreatorWorkspaceError,
                                              PathViolation, UnknownProject)

V = {"project_name": "Cafe Site", "description": "A nice cafe"}


def ok(action):
    return ApprovalDecision(action=action, approved=True, reviewer="user")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "ws"
        self.audit = AuditLogger()
        self.gate = SecurityGate(self.audit)
        self.ws = CreatorWorkspaceManager(self.root, self.gate, self.audit)
        self.gen = CodeGenerationManager(self.ws, self.gate, self.audit)
        self.pid = self.ws.create_project("demo")

    def tearDown(self):
        self._tmp.cleanup()

    def pdir(self, pid=None):
        return self.root / (pid or self.pid)

    def user_files(self, pid=None):
        pd = self.pdir(pid)
        return sorted(p.relative_to(pd).as_posix() for p in pd.rglob("*")
                      if p.is_file() and not p.relative_to(pd).as_posix().startswith(".creator/"))


class TestGeneration(Base):
    def test_every_template_generates_multi_file_projects(self):
        for t in self.gen.registry.list():
            pid = self.ws.create_project("p")
            rec = self.gen.generate(pid, t["template_id"], V)
            self.assertGreaterEqual(len(rec["written"]), 3 if t["template_id"] != "docs_bundle" else 3)
            self.assertEqual(self.user_files(pid), sorted(rec["written"]), t["template_id"])
            self.assertEqual(sorted(self.ws.manifest(pid)), sorted(rec["written"]))
            self.assertTrue(self.ws.verify_integrity(pid)["ok"])
            self.assertEqual(rec["support_level"], "scaffold")
            self.assertFalse(rec["executed"])
            self.assertFalse(rec["installed_dependencies"])
            self.assertFalse(rec["ai_generated"])
            self.assertEqual(rec["unvalidated_files"].count("README.md"), 0)

    def test_builtin_templates_have_no_undeclared_dependencies(self):
        for t in BUILTIN:
            pid = self.ws.create_project("p")
            rec = self.gen.generate(pid, t.template_id, V)
            dep = rec["dependency_analysis"]
            self.assertEqual(dep["python"]["undeclared"], [], t.template_id)
            self.assertEqual(dep["javascript"]["undeclared"], [], t.template_id)
            self.assertEqual(dep["parse_errors"], [], t.template_id)

    def test_generated_content_substituted_and_valid(self):
        rec = self.gen.generate(self.pid, "fastapi_backend", V)
        main = self.ws.read_file(self.pid, "app/main.py").decode()
        self.assertIn('title="Cafe Site"', main)
        for r in rec["validation"]:
            self.assertTrue(r["ok"], r)
        self.assertEqual({r["path"]: r["level"] for r in rec["validation"]}["app/main.py"], "parser")

    def test_python_app_package_path_from_name(self):
        rec = self.gen.generate(self.pid, "python_app", {"project_name": "Data Tool"})
        self.assertIn("src/data_tool/core.py", rec["written"])
        self.assertIn("pyproject.toml", rec["written"])

    def test_record_persisted(self):
        rec = self.gen.generate(self.pid, "static_website", V)
        names = self.ws.list_control_records(self.pid, "generations")
        self.assertEqual(len(names), 1)
        stored = self.ws.load_control_record(self.pid, "generations", names[0])
        self.assertEqual(stored["generation_id"], rec["generation_id"])
        json.dumps(stored)

    def test_registry_maps_project_types(self):
        reg = default_registry()
        self.assertEqual(reg.for_project_type("fastapi_backend").template_id, "fastapi_backend")
        self.assertIsNone(reg.for_project_type("desktop_app"))  # no template => no claim


class TestVariablesAndBoundary(Base):
    def test_hostile_variables_rejected(self):
        bad_names = ["../evil", "a/b", "", "1abc", "x" * 80, 'na"me', "a\nb", "n$ame", "@@{x}", "a\\b"]
        for n in bad_names:
            with self.assertRaises(GenerationError, msg=repr(n)):
                derive_variables({"project_name": n})
        for d in ['x"; import os', "a\nb", "${x}", "<script>", "", "x" * 200, "@@{pkg}", "a'b", "a{b}"]:
            with self.assertRaises(GenerationError, msg=repr(d)):
                derive_variables({"project_name": "Ok", "description": d})
        with self.assertRaises(GenerationError):
            derive_variables({"project_name": "Ok", "path": "../x"})
        self.assertFalse(self.user_files())

    def test_traversal_in_template_path_blocked_at_generation(self):
        evil = Template("evil_tpl", "1", "e", "python_app", "d", {"../escape.py": "x = 1\n", "ok.py": "y = 2\n"})
        self.gen.registry._t["evil_tpl"] = evil  # bypass registration validation on purpose
        with self.assertRaises(PathViolation):
            self.gen.generate(self.pid, "evil_tpl", V)
        self.assertFalse((self.root / "escape.py").exists())
        self.assertFalse((self.root.parent / "escape.py").exists())
        self.assertEqual(self.user_files(), [])  # all-or-nothing: ok.py not written
        self.assertTrue(any(r["action"] == "workspace_escape" and r["outcome"] == "denied"
                            for r in self.audit.records(self.pid)))

    def test_all_writes_stay_inside_workspace(self):
        other = self.ws.create_project("other")
        before = self.user_files(other)
        self.gen.generate(self.pid, "nextjs_app", V)
        self.assertEqual(self.user_files(other), before)
        outside = [p for p in Path(self._tmp.name).rglob("*") if p.is_file()
                   and self.root not in p.parents]
        self.assertEqual(outside, [])

    def test_unknown_project_and_template(self):
        with self.assertRaises(UnknownProject):
            self.gen.generate("../ws", "static_website", V)
        with self.assertRaises(UnknownProject):
            self.gen.generate("cre_" + "0" * 16, "static_website", V)
        with self.assertRaises(GenerationError):
            self.gen.generate(self.pid, "no_such_template", V)

    def test_symlink_planted_in_workspace_blocks_generation(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        os.symlink(outside, self.pdir() / "css")
        with self.assertRaises(PathViolation):
            self.gen.generate(self.pid, "static_website", V)
        self.assertEqual(list(outside.iterdir()), [])


class TestCollisions(Base):
    def test_second_generation_collides_without_changes(self):
        self.gen.generate(self.pid, "static_website", V)
        before = {f: self.ws.read_file(self.pid, f) for f in self.user_files()}
        with self.assertRaises(CollisionError):
            self.gen.generate(self.pid, "static_website", {"project_name": "Other Name"})
        self.assertEqual({f: self.ws.read_file(self.pid, f) for f in self.user_files()}, before)

    def test_user_owned_file_blocks_whole_generation(self):
        (self.pdir() / "index.html").write_text("USER")
        with self.assertRaises(CollisionError):
            self.gen.generate(self.pid, "static_website", V)
        self.assertEqual(self.user_files(), ["index.html"])
        self.assertEqual((self.pdir() / "index.html").read_text(), "USER")

    def test_regenerate_identical_is_noop_without_approval(self):
        self.gen.generate(self.pid, "static_website", V)
        rec = self.gen.generate(self.pid, "static_website", V, regenerate=True)
        self.assertEqual(rec["written"], [])
        self.assertEqual(len(rec["unchanged"]), 4)

    def test_regenerate_modified_needs_exact_approval(self):
        self.gen.generate(self.pid, "static_website", V)
        (self.pdir() / "index.html").write_text("edited by user")
        with self.assertRaises(ApprovalRequired):
            self.gen.generate(self.pid, "static_website", V, regenerate=True)
        with self.assertRaises(ApprovalRequired):
            self.gen.generate(self.pid, "static_website", V, regenerate=True, approval=ok("delete_file"))
        self.assertEqual((self.pdir() / "index.html").read_text(), "edited by user")
        rec = self.gen.generate(self.pid, "static_website", V, regenerate=True, approval=ok("overwrite_file"))
        self.assertEqual(rec["overwritten"], ["index.html"])
        self.assertIn("<title>Cafe Site</title>", (self.pdir() / "index.html").read_text())
        backups = list((self.pdir() / ".creator" / "backups").rglob("index.html"))
        self.assertEqual(backups[0].read_text(), "edited by user")

    def test_regenerate_over_untracked_user_file_needs_approval(self):
        (self.pdir() / "README.md").write_text("mine")
        with self.assertRaises(ApprovalRequired):
            self.gen.generate(self.pid, "docs_bundle", V, regenerate=True)
        self.assertEqual(self.user_files(), ["README.md"])

    def test_case_variant_and_directory_collisions(self):
        self.ws.write_file(self.pid, "Index.html", "x")
        with self.assertRaises(CollisionError):
            self.gen.generate(self.pid, "static_website", V)
        pid2 = self.ws.create_project("d")
        (self.pdir(pid2) / "css").write_text("a file named css")
        with self.assertRaises(CollisionError) as cm:
            self.gen.generate(pid2, "static_website", V)
        self.assertIn("is a file", str(cm.exception))
        self.assertEqual(self.user_files(pid2), ["css"])  # caught in preflight: nothing written


class TestAtomicFailure(Base):
    def _failing_write(self, fail_on):
        real = CreatorWorkspaceManager.write_file
        calls = {"n": 0}

        def wrapper(mgr, *a, **kw):
            calls["n"] += 1
            if calls["n"] == fail_on:
                raise OSError("disk full")
            return real(mgr, *a, **kw)
        return wrapper

    def test_failure_midway_leaves_no_partial_project(self):
        with mock.patch.object(CreatorWorkspaceManager, "write_file", self._failing_write(3)):
            with self.assertRaises(GenerationError) as cm:
                self.gen.generate(self.pid, "python_app", V)
        self.assertIn("rolled back", str(cm.exception))
        self.assertEqual(self.user_files(), [])
        self.assertEqual(self.ws.manifest(self.pid), {})
        self.assertEqual(self.ws.list_control_records(self.pid, "generations"), [])
        self.assertTrue(any(r["action"] == "generate" and r["outcome"] == "failed"
                            for r in self.audit.records(self.pid)))

    def test_failure_preserves_user_files(self):
        (self.pdir() / "notes.txt").write_text("mine")
        with mock.patch.object(CreatorWorkspaceManager, "write_file", self._failing_write(2)):
            with self.assertRaises(GenerationError):
                self.gen.generate(self.pid, "static_website", V)
        self.assertEqual(self.user_files(), ["notes.txt"])
        self.assertEqual((self.pdir() / "notes.txt").read_text(), "mine")

    def test_failed_regeneration_restores_previous_content(self):
        self.gen.generate(self.pid, "static_website", V)
        (self.pdir() / "index.html").write_text("edited html")
        (self.pdir() / "css" / "styles.css").write_text("edited css")
        with mock.patch.object(CreatorWorkspaceManager, "write_file", self._failing_write(2)):
            with self.assertRaises(GenerationError) as cm:
                self.gen.generate(self.pid, "static_website", V, regenerate=True,
                                  approval=ok("overwrite_file"))
        self.assertIn("rolled back", str(cm.exception))
        self.assertEqual((self.pdir() / "index.html").read_text(), "edited html")
        self.assertEqual((self.pdir() / "css" / "styles.css").read_text(), "edited css")  # 1st write was undone
        self.assertEqual(len(self.user_files()), 4)

    def test_checkpoint_of_drifted_file_is_restorable(self):
        self.ws.write_file(self.pid, "a.txt", "v1")
        (self.pdir() / "a.txt").write_text("edited outside creator")
        cid = self.ws.create_checkpoint(self.pid)
        self.ws.write_file(self.pid, "a.txt", "v2", overwrite=True, approval=ok("overwrite_file"))
        self.ws.rollback(self.pid, cid)
        self.assertEqual((self.pdir() / "a.txt").read_text(), "edited outside creator")
        self.assertTrue(self.ws.verify_integrity(self.pid)["ok"])

    def test_discard_created_requires_valid_token_and_skips_modified(self):
        with self.assertRaises(CreatorWorkspaceError):
            self.ws.discard_created(self.pid, "short")
        self.ws.write_file(self.pid, "a.txt", "1", op="t" * 32)
        self.ws.write_file(self.pid, "b.txt", "2", op="t" * 32)
        (self.pdir() / "b.txt").write_text("changed by user")
        self.assertEqual(self.ws.discard_created(self.pid, "t" * 32), ["a.txt"])
        self.assertEqual((self.pdir() / "b.txt").read_text(), "changed by user")
        self.assertEqual(self.ws.discard_created(self.pid, "x" * 32), [])


class TestTemplateValidation(unittest.TestCase):
    def setUp(self):
        self.reg = TemplateRegistry()

    def t(self, files, **kw):
        base = dict(template_id="t_one", version="1", name="n", project_type="python_app", description="d", files=files)
        base.update(kw)
        return Template(**base)

    def test_rejections(self):
        cases = {
            "syntax": self.t({"a.py": "def (:\n"}),
            "placeholder": self.t({"a.py": "x = '@@{secret}'\n"}),
            "path placeholder": self.t({"@@{nope}/a.py": "x = 1\n"}),
            "traversal": self.t({"../a.py": "x = 1\n"}),
            "absolute": self.t({"/etc/a.py": "x = 1\n"}),
            "control dir": self.t({".creator/a.json": "{}"}),
            "sensitive": self.t({".env": "A=1"}),
            "dup case": self.t({"A.py": "x = 1\n", "a.py": "x = 1\n"}),
            "bad json": self.t({"a.json": "{bad"}),
            "bad html": self.t({"a.html": "<div><span></div>"}),
            "full claim": self.t({"a.py": "x = 1\n"}, support_level="full"),
            "bad id": self.t({"a.py": "x = 1\n"}, template_id="Bad-ID"),
            "empty": self.t({}),
            "too many": self.t({f"f{i}.txt": "x" for i in range(100)}),
        }
        for label, tpl in cases.items():
            with self.assertRaises(TemplateError, msg=label):
                self.reg.register(tpl)
        self.assertEqual(self.reg.list(), [])

    def test_valid_and_duplicate(self):
        good = self.t({"a.py": "x = '@@{slug}'\n"})
        self.reg.register(good)
        with self.assertRaises(TemplateError):
            self.reg.register(good)
        with self.assertRaises(TemplateError):
            self.reg.get("missing")

    def test_defaults_all_valid(self):
        self.assertEqual(len(default_registry().list()), 9)


class TestSyntaxValidation(unittest.TestCase):
    CASES = [
        ("a.py", "x = 1\n", True), ("a.py", "def (", False), ("a.py", "x = (1,\n", False),
        ("a.json", '{"a": [1, 2]}', True), ("a.json", "{a: 1}", False),
        ("a.toml", 'a = "1"\n', True), ("a.toml", "a =\n", False),
        ("a.yaml", "a: 1\nb: [1, 2]\n", True), ("a.yaml", "a: [1, 2\n", False), ("a.yaml", "a:\n\t- b\n", False),
        ("a.html", "<html><body><p>x</p><br></body></html>", True), ("a.html", "<div><span></div>", False),
        ("a.html", "<div>", False), ("a.css", "a { b: c; }", True), ("a.css", "a { b: c;", False),
        ("a.css", "/* open", False), ("a.js", "const f = () => ({a: [1]});", True),
        ("a.js", "const s = `a${f(`n${1}`)}b`;", True), ("a.js", "function f({", False),
        ("a.js", "let s = 'abc\n", False), ("a.js", "const t = `open", False), ("a.js", "a = (1];", False),
        ("a.jsx", "const a = <p>Don't</p>;", True), ("a.sql", "CREATE TABLE t (id INT);", True),
        ("a.sql", "CREATE TABLE t (id INT)", False), ("a.sql", "CREATE TABLE t (id INT;", False),
        ("a.md", "# t\n```py\nx\n```\n", True), ("a.md", "```py\nx\n", False),
    ]

    def test_table(self):
        for path, content, expected in self.CASES:
            r = validate_content(path, content)
            self.assertEqual(r.ok, expected, (path, content, r.errors))
            self.assertTrue(r.validated)

    def test_unknown_extension_not_claimed_as_validated(self):
        r = validate_content("x.bin", "data")
        self.assertTrue(r.ok)
        self.assertFalse(r.validated)
        self.assertEqual(r.level, "none")

    def test_nul_byte_and_levels(self):
        self.assertFalse(validate_content("a.txt", "a\x00b").ok)
        self.assertEqual(validate_content("a.py", "x=1").level, "parser")
        self.assertEqual(validate_content("a.css", "a{}").level, "structural")

    def test_validation_never_executes_code(self):
        marker = Path(tempfile.gettempdir()) / "aliena_exec_marker_c3"
        marker.unlink(missing_ok=True)
        code = f"open({str(marker)!r}, 'w').write('x')\nimport os; os.system('true')\n"
        self.assertTrue(validate_content("evil.py", code).ok)
        analyze_dependencies({"evil.py": code})
        self.assertFalse(marker.exists())

    def test_deeply_nested_input_contained(self):
        r = validate_content("deep.py", "x = " + "(" * 5000 + "1" + ")" * 5000)
        self.assertIsInstance(r.ok, bool)

    def test_generation_rejects_invalid_rendered_output(self):
        # registered-by-bypass template whose rendered output is invalid
        tmp = tempfile.TemporaryDirectory()
        audit = AuditLogger()
        gate = SecurityGate(audit)
        ws = CreatorWorkspaceManager(Path(tmp.name), gate, audit)
        gen = CodeGenerationManager(ws, gate, audit)
        gen.registry._t["bad_syn"] = Template("bad_syn", "1", "b", "python_app", "d",
                                              {"ok.py": "x = 1\n", "bad.py": "def (:\n"})
        pid = ws.create_project("p")
        with self.assertRaises(GenerationError):
            gen.generate(pid, "bad_syn", V)
        self.assertEqual(ws.manifest(pid), {})
        self.assertTrue(any(r["outcome"] == "rejected" for r in audit.records(pid)))
        tmp.cleanup()


class TestAnalysis(unittest.TestCase):
    def test_python_classification(self):
        files = {"requirements.txt": "FastAPI>=1\nPyYAML\n",
                 "app/main.py": "import os, sys\nimport yaml\nimport fastapi.testclient\nimport requests\nfrom app import util\nfrom . import rel\n",
                 "app/util.py": ""}
        r = analyze_dependencies(files)["python"]
        self.assertEqual(r["third_party_imports"], ["fastapi", "requests", "yaml"])
        self.assertEqual(r["undeclared"], ["requests"])

    def test_pyproject_dependencies(self):
        files = {"pyproject.toml": '[project]\nname="x"\nversion="1"\ndependencies=["requests>=2"]\n',
                 "x.py": "import requests\n"}
        self.assertEqual(analyze_dependencies(files)["python"]["undeclared"], [])

    def test_js_classification(self):
        files = {"package.json": '{"dependencies": {"react": "1"}}',
                 "src/a.jsx": "import React from 'react';\nimport x from './x';\nimport '@scope/pkg/sub';\n"
                              "import fs from 'node:fs';\nconst l = require('lodash/fp');\nimport a from '@/alias';\n"}
        r = analyze_dependencies(files)["javascript"]
        self.assertEqual(r["undeclared"], ["@scope/pkg", "lodash"])

    def test_syntax_error_reported_not_raised(self):
        r = analyze_dependencies({"a.py": "def ("})
        self.assertTrue(r["parse_errors"])


class TestSecurityAndAudit(Base):
    def test_gate_and_audit_records(self):
        rec = self.gen.generate(self.pid, "python_app", V)
        acts = [(r["action"], r["outcome"]) for r in self.audit.records(self.pid)]
        self.assertIn(("generate_project_files", "allowed"), acts)
        self.assertIn(("write_generated_file", "allowed"), acts)
        self.assertIn(("generate", "ok"), acts)
        self.assertTrue(self.audit.verify_chain())
        self.assertIn(rec["content_digest"][:12], [r for r in self.audit.records(self.pid)
                                                   if r["action"] == "generate"][-1]["detail"])

    def test_collision_and_denial_audited(self):
        self.gen.generate(self.pid, "static_website", V)
        with self.assertRaises(CollisionError):
            self.gen.generate(self.pid, "static_website", V)
        self.assertTrue(any(r["action"] == "generate" and r["outcome"] == "collision"
                            for r in self.audit.records(self.pid)))
        (self.pdir() / "index.html").write_text("e")
        with self.assertRaises(ApprovalRequired):
            self.gen.generate(self.pid, "static_website", V, regenerate=True)
        self.assertTrue(any(r["action"] == "overwrite_file" and r["outcome"] == "denied"
                            for r in self.audit.records(self.pid)))

    def test_generation_blocked_if_gate_denies(self):
        class DenyAll(SecurityGate):
            def check(self, project_id, actor, action, approval=None):
                d = super().check(project_id, actor, action, approval)
                if action == "generate_project_files":
                    from jarvis.creator.security_gate import GateDecision
                    return GateDecision(action, False, "denied by test")
                return d
        gen = CodeGenerationManager(self.ws, DenyAll(self.audit), self.audit)
        with self.assertRaises(ApprovalRequired):
            gen.generate(self.pid, "static_website", V)
        self.assertEqual(self.user_files(), [])

    def test_execution_still_blocked_regardless_of_approval(self):
        for action in ("execute_code", "run_generated_script", "install_dependencies_auto"):
            self.assertFalse(self.gate.check(self.pid, "codegen", action, ok(action)).allowed)

    def test_no_execution_primitives_in_creator_sources(self):
        banned = ("subprocess", "os.system", "os.popen", "eval(", "exec(", "shell=True", "import socket",
                  "urllib", "requests.", "importlib", "__import__", "runpy", "pip install")
        for name in ("codegen_manager.py", "templates.py", "validators.py", "analysis.py", "workspace_manager.py"):
            src = (Path(cg.__file__).parent / name).read_text()
            for b in banned:
                self.assertNotIn(b, src, f"{b} in {name}")

    def test_generation_does_not_leave_temp_files_or_pycache(self):
        self.gen.generate(self.pid, "python_app", V)
        self.assertEqual(list(self.pdir().rglob(".tmp_*")), [])
        self.assertEqual(list(self.pdir().rglob("__pycache__")), [])

    def test_control_records_reject_bad_names(self):
        for kind, name in (("../x", "a"), ("generations", "../a"), ("other", "a"), ("generations", "")):
            with self.assertRaises(CreatorWorkspaceError):
                self.ws.save_control_record(self.pid, kind, name, {})


class TestReproducibility(Base):
    def test_same_inputs_same_output_across_projects(self):
        p2 = self.ws.create_project("second")
        a = self.gen.generate(self.pid, "react_app", V)
        b = self.gen.generate(p2, "react_app", V)
        self.assertEqual(a["content_digest"], b["content_digest"])
        self.assertEqual(a["generation_id"], b["generation_id"])
        for f in a["written"]:
            self.assertEqual(self.ws.read_file(self.pid, f), self.ws.read_file(p2, f))

    def test_different_inputs_differ(self):
        p2 = self.ws.create_project("second")
        a = self.gen.generate(self.pid, "react_app", V)
        b = self.gen.generate(p2, "react_app", {"project_name": "Other"})
        self.assertNotEqual(a["content_digest"], b["content_digest"])
        self.assertNotEqual(a["generation_id"], b["generation_id"])

    def test_no_timestamps_or_random_data_in_output(self):
        self.gen.generate(self.pid, "python_app", V)
        for f in self.user_files():
            text = self.ws.read_file(self.pid, f).decode()
            self.assertNotRegex(text, r"20\d\d-\d\d-\d\d")

    def test_verify_generation_and_drift(self):
        self.gen.generate(self.pid, "fastapi_backend", V)
        name = self.ws.list_control_records(self.pid, "generations")[0]
        self.assertEqual(self.gen.verify_generation(self.pid, name), {"reproducible": True, "drift": [], "ok": True})
        (self.pdir() / "app" / "main.py").write_text("# changed\n")
        r = self.gen.verify_generation(self.pid, name)
        self.assertTrue(r["reproducible"])
        self.assertEqual(r["drift"], ["app/main.py"])
        self.assertFalse(r["ok"])

    def test_template_version_change_detected(self):
        self.gen.generate(self.pid, "docs_bundle", V)
        name = self.ws.list_control_records(self.pid, "generations")[0]
        old = self.gen.registry._t["docs_bundle"]
        self.gen.registry._t["docs_bundle"] = Template(old.template_id, "2.0.0", old.name, old.project_type,
                                                       old.description, old.files)
        self.assertFalse(self.gen.verify_generation(self.pid, name)["reproducible"])


if __name__ == "__main__":
    unittest.main()
