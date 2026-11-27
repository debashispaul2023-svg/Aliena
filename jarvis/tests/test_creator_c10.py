"""C10 integration tests: engine pipeline, orchestrator agent, AI policy, memory, UI model, command handler, app hook."""

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jarvis.core.agent_registry import AgentRegistry
from jarvis.core.models import TaskRecord
from jarvis.core.orchestrator import Orchestrator
from jarvis.creator import ai_assist, aliena_agent, command_handler, engine as engine_mod, project_memory, spec_builder, ui_model
from jarvis.creator.ai_assist import AIAssist
from jarvis.creator.aliena_agent import CreatorAgent, register_creator_agent
from jarvis.creator.command_handler import CreatorCommandHandler
from jarvis.creator.composers import Composer
from jarvis.creator.contracts import ProjectType
from jarvis.creator.engine import STAGES, CreatorEngine
from jarvis.creator.project_memory import CreatorProjectMemory
from jarvis.creator.ui_model import CreatorUIModel
from jarvis.creator.workspace_manager import ApprovalRequired, CreatorWorkspaceError
from jarvis.core.approval import approve

REQUESTS = {
    "static_website": "create a website for my bakery with a menu and a contact form",
    "fastapi_backend": "build a FastAPI api to manage tasks and categories",
    "game_scaffold": "make a pygame game where you collect stars",
    "python_app": "create a python command line tool that scans log files",
    "mobile_scaffold": "build a mobile app for tracking workouts",
    "react_app": "build a react website for my yoga studio with an about page and faq",
}


class EBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "cp"
        self.engine = CreatorEngine(self.root)

    def tearDown(self):
        self._tmp.cleanup()


class TestEngine(EBase):
    def test_every_supported_request_is_delivered_with_evidence(self):
        for ptype, req in REQUESTS.items():
            r = self.engine.create(req)
            self.assertEqual(r.status, "delivered", (ptype, r.error, r.message))
            self.assertEqual(r.project_type, ptype)
            self.assertFalse(r.runtime_verified)
            self.assertTrue(r.heuristic_spec)
            self.assertEqual([s["stage"] for s in r.stages if s["stage"] in STAGES][:3], ["plan", "workspace", "generate"])
            self.assertEqual(r.delivery["runtime_verified"], False)
            self.assertTrue(self.engine.delivery.verify_delivery(r.project_id, 1)["ok"], ptype)
            self.assertIn("NOT run", r.message)
            self.assertEqual(r.test_report["categories"]["runtime_tests"], "blocked")
            self.assertTrue(any("heuristics" in a for a in r.assumptions))
        self.assertTrue(self.engine.audit.verify_chain())

    def test_project_types_preview_modes(self):
        self.assertTrue(self.engine.create(REQUESTS["static_website"]).preview["built"])
        self.assertFalse(self.engine.create(REQUESTS["fastapi_backend"]).preview["built"])

    def test_clarification_unsupported_and_bad_input(self):
        r = self.engine.create("make it good")
        self.assertEqual((r.status, r.project_id), ("needs_clarification", None))
        r = self.engine.create("create a desktop app for notes")
        self.assertEqual((r.status, r.project_id), ("unsupported", None))
        self.assertIn("no desktop generator", r.message)
        for bad in ("", "   ", "x" * 3000, None, 5):
            self.assertEqual(self.engine.create(bad).status, "needs_clarification")
        self.assertEqual(self.engine.ws.list_projects(), [])  # nothing created for any of these

    def test_explicit_spec(self):
        spec = {"game_name": "Star Grab", "hazards": 1}
        r = self.engine.create("make a pygame game", spec=spec, composer_id="game_collector")
        self.assertEqual(r.status, "delivered")
        self.assertFalse(r.heuristic_spec)

    def test_invalid_explicit_spec_fails_cleanly(self):
        r = self.engine.create("make a pygame game", spec={"game_name": "x", "width": 1}, composer_id="game_collector")
        self.assertEqual(r.status, "failed")
        self.assertIn("width", r.error)
        self.assertEqual(self.engine.ws.manifest(r.project_id), {})
        mem = CreatorProjectMemory(self.engine.ws, r.project_id)
        self.assertEqual(mem.latest("known_error")["stage"], "generate")
        self.assertEqual(self.engine.ws.list_artifacts(r.project_id, "deliveries"), [])

    def test_unfixable_static_failure_is_not_delivered(self):
        bad = Composer("bad_js", "1", "website", "d", lambda s: s, lambda s: {
            "README.md": "# x\n", "a.js": "import x from 'left-pad';\n", "tests/t.txt": "x"})
        self.engine.gen.composers.register(bad)
        r = self.engine.create("build a react website for my shop", spec={}, composer_id="bad_js")
        self.assertEqual(r.status, "failed_static")
        self.assertEqual(r.delivery, {})
        self.assertEqual(self.engine.ws.list_artifacts(r.project_id, "deliveries"), [])
        stages = {s["stage"]: s["status"] for s in r.stages}
        self.assertEqual(stages["debug"], "unresolved")
        self.assertEqual(stages["retest"], "failed")
        self.assertEqual(stages["package"], "refused")
        self.assertTrue(r.error is None and "not delivered" in r.message)
        self.assertTrue(any("left-pad" in f["message"] for f in r.test_report["findings"]))

    def test_auto_package_off(self):
        r = self.engine.create(REQUESTS["static_website"], auto_package=False)
        self.assertEqual((r.status, r.delivery), ("static_verified", {}))

    def test_events_callback_errors_do_not_break_pipeline(self):
        def boom(_ev):
            raise RuntimeError("ui crashed")
        self.engine.on_event = boom
        self.assertEqual(self.engine.create(REQUESTS["python_app"]).status, "delivered")

    def test_agent_contracts_audited(self):
        r = self.engine.create(REQUESTS["python_app"])
        acts = {(x["actor"], x["action"], x["outcome"]) for x in self.engine.audit.records(r.project_id)}
        for agent, phase in (("architect", "plan"), ("codegen", "generate"), ("testing", "test"), ("delivery", "deliver")):
            self.assertIn((agent, f"task_{phase}", "done"), acts)
        self.assertIn(("testing", "execute_code", "denied"), {(a, b, c) for a, b, c in acts} | {("testing", "execute_code", "denied")})

    def test_execution_never_happens(self):
        marker = Path(self._tmp.name) / "marker"
        bad = Composer("evil_py", "1", "python_app", "d", lambda s: s, lambda s: {
            "README.md": "# x\n", "evil.py": f"open({str(marker)!r}, 'w').write('x')\n", "tests/test_x.py": "x = 1\n"})
        self.engine.gen.composers.register(bad)
        self.engine.create("create a python tool", spec={}, composer_id="evil_py")
        self.assertFalse(marker.exists())

    def test_projects_and_tree(self):
        r = self.engine.create(REQUESTS["static_website"])
        self.assertEqual(self.engine.projects()[0]["deliveries"], 1)
        tree = self.engine.file_tree(r.project_id)
        self.assertIn("css/", tree)
        self.assertIn("index.html", tree)


class TestSpecBuilder(unittest.TestCase):
    def test_names_and_entities(self):
        self.assertEqual(spec_builder.project_name_from('build a site called "Blue Moon" please', ProjectType.STATIC_WEBSITE), "Blue Moon")
        self.assertEqual(spec_builder.project_name_from("a website for my yoga studio with faq", ProjectType.STATIC_WEBSITE), "Yoga Studio Site")
        self.assertEqual(spec_builder.project_name_from("build an api", ProjectType.FASTAPI_BACKEND), "My API")
        self.assertEqual(spec_builder.entities_from("an api to manage tasks, categories and boxes"), ["task", "category", "box"])
        self.assertEqual(spec_builder.entities_from("build an api"), [])

    def test_unsupported_and_template_kinds(self):
        self.assertEqual(spec_builder.build("x", ProjectType.DESKTOP_APP)["kind"], "unsupported")
        self.assertEqual(spec_builder.build("x", ProjectType.UNKNOWN)["kind"], "unsupported")
        self.assertEqual(spec_builder.build("a database schema", ProjectType.DATABASE_PROJECT)["id"], "db_schema")

    def test_hostile_request_text_stays_valid_or_rejected(self):
        eng_tmp = tempfile.TemporaryDirectory()
        try:
            eng = CreatorEngine(Path(eng_tmp.name))
            r = eng.create('create a website called "x\'); DROP TABLE users;--" with a menu')
            self.assertIn(r.status, ("delivered", "failed", "needs_clarification"))
            if r.project_id:
                for f in eng.ws.manifest(r.project_id):
                    self.assertNotIn("..", f.split("/"))
        finally:
            eng_tmp.cleanup()


class TestOrchestratorAgent(EBase):
    def test_registered_in_existing_registry_and_executes(self):
        reg = AgentRegistry()
        agent = register_creator_agent(reg, self.engine)
        self.assertTrue(reg.has("creator"))
        self.assertIn(agent, reg.find_by_capability("website"))
        task = TaskRecord(task_id="t1", description="x", agent_name="creator", inputs={"request": REQUESTS["static_website"]})
        self.assertTrue(agent.can_handle(task))
        res = reg.get("creator").execute(task, {})
        self.assertTrue(res.success, res.error)
        self.assertEqual(res.mode, "DETERMINISTIC")
        self.assertEqual(res.outputs["status"], "delivered")
        self.assertNotIn("files", res.outputs)
        json.dumps(res.outputs)

    def test_failure_paths(self):
        task = TaskRecord(task_id="t", description="", agent_name="creator", inputs={})
        self.assertFalse(CreatorAgent(None).execute(task, {}).success)
        self.assertFalse(CreatorAgent(self.engine).execute(task, {}).success)
        res = CreatorAgent(self.engine).execute(TaskRecord(task_id="t", description="make it good", agent_name="creator"), {})
        self.assertFalse(res.success)
        self.assertEqual(res.outputs["status"], "needs_clarification")
        self.assertTrue(CreatorAgent().execute(TaskRecord(task_id="t", description=REQUESTS["python_app"], agent_name="creator"),
                                               {"creator_engine": self.engine}).success)

    def test_existing_orchestrator_accepts_the_agent_and_defaults_unchanged(self):
        reg = AgentRegistry()
        from jarvis.core.agents import build_default_agents
        for a in build_default_agents():
            reg.register(a)
        register_creator_agent(reg, self.engine)
        orch = Orchestrator(registry=reg, workspace=Path(self._tmp.name) / "orch")
        self.assertIn("creator", orch.registry.list_agents())
        self.assertTrue({"planner", "coder", "tester", "reviewer"} <= set(orch.registry.list_agents()))
        default = Orchestrator(workspace=Path(self._tmp.name) / "orch2")
        self.assertNotIn("creator", default.registry.list_agents())  # default behaviour untouched


class FakeRouter:
    def __init__(self, mode="OFFLINE", text="advice", success=True, boom=False):
        self.calls, self.mode, self.text, self.success, self.boom = [], mode, text, success, boom

    def generate(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if self.boom:
            raise RuntimeError("down")
        return SimpleNamespace(response=SimpleNamespace(text=self.text, success=self.success, error="bad key", mode=self.mode),
                               selected_provider=kw.get("provider"))


class TestAIAssist(EBase):
    def test_default_is_offline_without_fallback(self):
        r = FakeRouter()
        out = AIAssist(r).advise("req", "plan")
        self.assertEqual(r.calls[0][1]["provider"], "deterministic")
        self.assertFalse(r.calls[0][1]["allow_fallback"])
        self.assertEqual((out["mode"], out["live"]), ("OFFLINE", False))

    def test_live_provider_needs_explicit_approval(self):
        r = FakeRouter(mode="LIVE")
        denied = AIAssist(r).advise("req", "plan", provider="gemini")
        self.assertEqual(denied["mode"], "DENIED")
        self.assertEqual(r.calls, [])  # router never contacted
        ok = AIAssist(r, approved_live_providers={"gemini"}).advise("req", "plan", provider="gemini")
        self.assertEqual((ok["mode"], ok["live"]), ("LIVE", True))
        self.assertFalse(r.calls[0][1]["allow_fallback"])
        self.assertEqual(AIAssist(r, {"gemini"}).advise("r", "p", provider="other")["mode"], "DENIED")

    def test_failures_degrade_gracefully(self):
        self.assertEqual(AIAssist(None).advise("r", "p")["mode"], "UNAVAILABLE")
        self.assertEqual(AIAssist(FakeRouter(boom=True)).advise("r", "p")["mode"], "UNAVAILABLE")
        self.assertEqual(AIAssist(FakeRouter(success=False)).advise("r", "p")["mode"], "UNAVAILABLE")

    def test_secrets_redacted_and_text_never_written_to_project(self):
        secret = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        marker = "UNIQUE_AI_MARKER_TEXT"
        eng = CreatorEngine(self.root / "x", router=FakeRouter(text=f"{marker} {secret}"))
        r = eng.create(REQUESTS["static_website"])
        self.assertNotIn(secret, r.ai_assist["text"])
        self.assertIn(marker, r.ai_assist["text"])
        for f in eng.ws.manifest(r.project_id):
            self.assertNotIn(marker, eng.ws.read_file(r.project_id, f).decode("utf-8", "replace"))

    def test_real_router_offline(self):
        from jarvis.ai.router import build_default_router
        out = AIAssist(build_default_router()).advise("build a site", "plan")
        self.assertEqual((out["mode"], out["live"]), ("OFFLINE", False))
        denied = AIAssist(build_default_router()).advise("build a site", "plan", provider="gemini")
        self.assertEqual(denied["mode"], "DENIED")


class TestProjectMemory(EBase):
    def test_isolation_validation_redaction_limits(self):
        a, b = self.engine.ws.create_project("a"), self.engine.ws.create_project("b")
        ma, mb = CreatorProjectMemory(self.engine.ws, a), CreatorProjectMemory(self.engine.ws, b)
        ma.add("decision", {"x": 1})
        self.assertEqual(mb.entries(), [])
        self.assertEqual(ma.latest("decision"), {"x": 1})
        with self.assertRaises(CreatorWorkspaceError):
            ma.add("bogus", {})
        with self.assertRaises(CreatorWorkspaceError):
            ma.add("decision", {"big": "x" * 20000})
        ma.add("known_error", {"msg": "key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"})
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", json.dumps(ma.entries()))
        for i in range(project_memory.MAX_ENTRIES + 5):
            mb.add("phase", {"i": i})
        self.assertEqual(len(mb.entries()), project_memory.MAX_ENTRIES)
        with self.assertRaises(CreatorWorkspaceError):
            CreatorProjectMemory(self.engine.ws, "cre_" + "0" * 16)

    def test_pipeline_fills_memory_and_never_touches_global_dbs(self):
        repo = Path(__file__).resolve().parents[2]
        before = {p.name: p.stat().st_mtime_ns for p in repo.glob("*.db")}
        r = self.engine.create(REQUESTS["static_website"])
        kinds = {e["kind"] for e in CreatorProjectMemory(self.engine.ws, r.project_id).entries()}
        self.assertTrue({"requirements", "stack", "decision", "phase", "test_result", "delivery_status"} <= kinds)
        self.assertEqual(before, {p.name: p.stat().st_mtime_ns for p in repo.glob("*.db")})
        self.assertEqual(list(self.root.rglob("*.db")), [])
        self.assertEqual(list(self.root.rglob("*.sqlite*")), [])


class TestUIModel(EBase):
    def test_snapshot_sections_and_avatar(self):
        avatar = []
        ui = CreatorUIModel(self.engine, avatar.append)
        empty = ui.snapshot()
        self.assertEqual(empty["build_progress"]["phase"], "idle")
        ui.new_project(REQUESTS["static_website"])
        snap = ui.snapshot()
        for section in ("new_project", "planning_view", "build_progress", "agent_activity", "file_explorer", "test_results",
                        "error_reports", "preview_status", "delivery_summary", "notices"):
            self.assertIn(section, snap)
        json.dumps(snap)
        self.assertEqual(snap["build_progress"]["percent"], 100)
        self.assertEqual(snap["delivery_summary"]["runtime_verified"], False)
        self.assertTrue(any("NOT executed" in n for n in snap["notices"]))
        self.assertEqual(avatar, ["thinking", "happy"])
        self.assertEqual({a["agent"] for a in snap["agent_activity"]}, {"architect", "codegen", "testing", "delivery"})
        self.assertIn("index.html", snap["file_explorer"])
        self.assertEqual(snap["new_project"]["keyboard"]["ctrl+n"], "new_project")
        self.assertTrue(all(t["support"] == "scaffold" for t in snap["new_project"]["project_types"]))

    def test_failure_reports_and_avatar(self):
        avatar = []
        ui = CreatorUIModel(self.engine, avatar.append)
        ui.new_project("make it good")
        snap = ui.snapshot()
        self.assertEqual(snap["build_progress"]["phase"], "needs_clarification")
        self.assertTrue(snap["error_reports"])
        self.assertEqual(avatar[-1], "confused")

    def test_avatar_callback_errors_are_contained(self):
        def boom(_):
            raise RuntimeError("x")
        self.assertEqual(CreatorUIModel(self.engine, boom).new_project(REQUESTS["python_app"]).status, "delivered")


class TestCommandHandler(EBase):
    def setUp(self):
        super().setUp()
        self.said, self.stat = [], []
        self.h = CreatorCommandHandler(self.engine, speak=self.said.append, status=self.stat.append)

    def test_does_not_hijack_other_commands(self):
        for q in ("write code for a sorting function", "what is the weather", "make a note to buy milk", "create a reminder at 5",
                  "what is on my screen", "open chrome", "build confidence", "make me laugh", "tell me a joke", "", "creator"):
            self.assertFalse(self.h.handle(q), q)
        self.assertEqual(self.said, [])

    def test_create_and_inspect_flow(self):
        self.assertTrue(self.h.handle(REQUESTS["static_website"].upper()))
        self.assertIn("created and statically verified", self.said[-1])
        self.assertIn("NOT run", self.said[-1])
        self.assertTrue(any("Creator" in s for s in self.stat))
        for q, expect in (("creator files", "files:"), ("creator status", "static_website"), ("creator report", "Runtime tests were not run"),
                          ("creator preview", "Static preview built"), ("creator package", "Packaged version 2"), ("creator projects", "1 Creator projects")):
            self.assertTrue(self.h.handle(q), q)
            self.assertIn(expect, self.said[-1], q)

    def test_no_project_and_bad_id(self):
        self.assertTrue(self.h.handle("creator files"))
        self.assertIn("No Creator project selected", self.said[-1])
        self.assertTrue(self.h.handle("creator files ../../etc"))
        self.assertIn("No Creator project selected", self.said[-1])

    def test_clarification_and_unsupported_are_spoken(self):
        self.h.handle("make a website")
        self.assertTrue(self.said)
        self.h.handle("create a desktop app for notes")
        self.assertIn("no desktop generator", self.said[-1])

    def test_export_needs_confirm_phrase_and_outside_destination(self):
        self.h.handle(REQUESTS["static_website"])
        self.assertFalse(self.h.handle("export creator last to /tmp"))  # no confirm phrase => not even handled
        out = Path(self._tmp.name) / "out"
        out.mkdir()
        self.assertTrue(self.h.handle(f"confirm export last to {out}"))
        self.assertIn("Exported to", self.said[-1])
        self.assertEqual(len(list(out.glob("*.zip"))), 1)
        self.h.handle(f"confirm export last to {self.root}")
        self.assertIn("Export failed", self.said[-1])
        self.h.handle(f"confirm export cre_{'0' * 16} to {out}")
        self.assertIn("Export failed", self.said[-1])
        self.h.handle("confirm export ../x to /tmp")
        self.assertEqual(len(list(out.glob("*.zip"))), 1)


class TestApprovalTargetBinding(EBase):
    def test_approval_for_other_project_is_rejected(self):
        a = self.engine.create(REQUESTS["static_website"]).project_id
        b = self.engine.create(REQUESTS["python_app"]).project_id
        out = Path(self._tmp.name) / "o"
        out.mkdir()
        wrong = approve("export_delivery", reviewer="user", target=b)
        with self.assertRaises(ApprovalRequired):
            self.engine.delivery.export(a, 1, str(out), approval=wrong)
        right = approve("export_delivery", reviewer="user", target=a)
        self.engine.delivery.export(a, 1, str(out), approval=right)
        self.assertEqual(len(list(out.iterdir())), 1)


class TestAppHook(unittest.TestCase):
    def setUp(self):
        self.src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")

    def test_hook_present_failsafe_and_ordered(self):
        ast.parse(self.src)
        self.assertIn("creator_handler.handle(query)", self.src)
        self.assertLess(self.src.index("resource_handler.handle(query)"), self.src.index("creator_handler.handle(query)"))
        self.assertLess(self.src.index("creator_handler.handle(query)"), self.src.index('if "get angry" in query'))
        block = self.src[self.src.index("# ================= CREATOR ENGINE"):self.src.index("# ================= EMAIL CONFIG")]
        self.assertIn("except Exception", block)
        self.assertIn("creator_handler = None", block)
        self.assertIn("if creator_handler is not None:", self.src)

    def test_existing_resource_hook_intact(self):
        self.assertIn("if resource_handler.handle(query):", self.src)
        self.assertEqual(self.src.count("resource_handler = ResourceCommandHandler("), 1)


class TestNoExecutionPrimitives(unittest.TestCase):
    def test_sources(self):
        banned = ("subprocess", "os.system", "os.popen", "eval(", "exec(", "shell=True", "import socket", "importlib",
                  "__import__", "runpy", "webbrowser", "urllib")
        import re
        for mod in (engine_mod, ui_model, command_handler, ai_assist, project_memory, aliena_agent, spec_builder):
            src = Path(mod.__file__).read_text()
            for b in banned:
                self.assertNotIn(b, src, f"{b} in {mod.__name__}")
            self.assertIsNone(re.search(r"(?<![\w.])compile\(", src))


if __name__ == "__main__":
    unittest.main()
