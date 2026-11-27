"""C5/C6 composer tests: FastAPI backend, Python software, mobile, game."""

import ast
import json
import tomllib
import unittest

from jarvis.creator.codegen_manager import GenerationError
from jarvis.creator.compose_apps import norm_game, norm_mobile, norm_python, safe_pkg
from jarvis.creator.compose_backend import normalize as norm_api
from jarvis.creator.spec_utils import SpecError
from jarvis.creator.validators import validate_content
from jarvis.tests.creator_testkit import CreatorBase

API = {"project_name": "Task Tracker", "description": "Tracks \"tasks\" & <more>",
       "entities": [{"name": "task", "fields": [{"name": "title", "type": "str"}, {"name": "done", "type": "bool", "required": False}]},
                    {"name": "category", "fields": [{"name": "label"}, {"name": "weight", "type": "float"}]}]}
PY = {"project_name": "Log Tool", "description": 'Scans "logs"\nand more', "commands": [{"name": "scan"}, {"name": "report", "description": "Make a report"}]}
MOBILE = {"app_name": "Fit Track", "description": "Tracker", "theme": {"primary": "#0a7"[:0] or "#00aa77"},
          "screens": [{"name": "home", "kind": "text", "text": "Hi </script> there"},
                      {"name": "log", "kind": "list", "items": [{"title": "Run", "text": "5k"}]},
                      {"name": "add", "kind": "form", "fields": [{"name": "note", "label": "Note"}]}]}
GAME = {"game_name": "Star Grab", "hazards": 2, "lives": 3}


class TestApiSpec(unittest.TestCase):
    def bad(self, **kw):
        with self.assertRaises(SpecError, msg=str(kw)[:100]):
            norm_api({**API, **kw})

    def test_rejections(self):
        for name in ("Task", "drop table", "task;--", "order", "class", "t" * 40, "1abc", "", "../x", "id"):
            self.bad(entities=[{"name": name, "fields": [{"name": "a"}]}])
        self.bad(entities=[])
        self.bad(entities=[{"name": "a", "fields": []}])
        self.bad(entities=[{"name": "task", "fields": [{"name": "id"}]}])
        self.bad(entities=[{"name": "task", "fields": [{"name": "select"}]}])
        self.bad(entities=[{"name": "task", "fields": [{"name": "a"}, {"name": "a"}]}])
        self.bad(entities=[{"name": "task", "fields": [{"name": "a", "type": "blob"}]}])
        self.bad(entities=[{"name": "task", "fields": [{"name": "a"}]}] * 2)
        self.bad(extra=1)

    def test_plurals(self):
        n = norm_api({"project_name": "p", "entities": [{"name": "category", "fields": [{"name": "a"}]},
                                                        {"name": "bus", "fields": [{"name": "a"}]}]})
        self.assertEqual([e["table"] for e in n["entities"]], ["categories", "buses"])


class TestFastApi(CreatorBase):
    def test_generation(self):
        rec = self.gen.compose(self.pid, "fastapi_service", API)
        for f in ("app/main.py", "app/schemas.py", "app/repository.py", "app/routers/task.py", "app/routers/category.py",
                  "db/schema.sql", "db/migrations/0001_initial.up.sql", "tests/conftest.py", "tests/test_api.py",
                  "requirements.txt", "env.example", "docs/API.md"):
            self.assertIn(f, rec["written"])
        self.assertTrue(all(v["ok"] for v in rec["validation"]))
        self.assertEqual(rec["dependency_analysis"]["python"]["undeclared"], [])
        self.assertEqual(self.ws.verify_integrity(self.pid)["ok"], True)

    def test_structure_via_ast(self):
        self.gen.compose(self.pid, "fastapi_service", API)
        schemas = ast.parse(self.text("app/schemas.py"))
        classes = {n.name for n in schemas.body if isinstance(n, ast.ClassDef)}
        self.assertTrue({"TaskCreate", "TaskUpdate", "TaskOut", "CategoryOut"} <= classes)
        router = ast.parse(self.text("app/routers/task.py"))
        funcs = {n.name for n in router.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(funcs, {"list_items", "create_item", "get_item", "update_item", "delete_item"})
        tests = ast.parse(self.text("tests/test_api.py"))
        names = {n.name for n in tests.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue({"test_task_crud", "test_task_not_found", "test_task_validation", "test_category_crud"} <= names)
        self.assertIn("include_router(task_router.router)", self.text("app/main.py"))

    def test_sql_is_parameterised_and_identifiers_quoted(self):
        self.gen.compose(self.pid, "fastapi_service", API)
        repo = self.text("app/repository.py")
        self.assertIn("VALUES ({marks})", repo)
        self.assertNotIn("% ", repo)
        self.assertNotIn(".format(", repo)
        schema = self.text("db/schema.sql")
        self.assertIn('CREATE TABLE IF NOT EXISTS "tasks"', schema)
        self.assertIn('"done" INTEGER', schema)
        self.assertIn('"title" TEXT NOT NULL', schema)
        self.assertIn('"categories"', schema)

    def test_hostile_description_is_safe_python(self):
        self.gen.compose(self.pid, "fastapi_service", {**API, "project_name": "Bad\"; import os #"})
        tree = ast.parse(self.text("app/config.py"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imported, {"os", "dataclasses"})  # hostile text stayed inside a string literal

    def test_no_secrets_and_no_auth_claim(self):
        self.gen.compose(self.pid, "fastapi_service", API)
        self.assertIn("No authentication is generated", self.text("docs/API.md"))
        self.assertNotIn("SECRET", self.text("env.example").upper().replace("NEVER COMMIT REAL SECRETS", ""))
        self.assertIn(".env", self.text(".gitignore"))

    def test_reproducible(self):
        p2 = self.ws.create_project("b")
        a, b = self.gen.compose(self.pid, "fastapi_service", API), self.gen.compose(p2, "fastapi_service", API)
        self.assertEqual(a["content_digest"], b["content_digest"])
        self.assertTrue(self.gen.verify_generation(self.pid, self.ws.list_control_records(self.pid, "generations")[0])["ok"])


class TestPythonSoftware(CreatorBase):
    def test_spec_rejections(self):
        for bad in ({"commands": []}, {"commands": [{"name": "Scan"}]}, {"commands": [{"name": "a"}, {"name": "a"}]},
                    {"commands": [{"name": "registry"}]}, {"commands": [{"name": "def"}]}, {"log_level": "TRACE"}, {"x": 1}):
            with self.assertRaises(SpecError, msg=str(bad)):
                norm_python({**PY, **bad})

    def test_generation_and_structure(self):
        rec = self.gen.compose(self.pid, "python_software", PY)
        for f in ("pyproject.toml", "src/log_tool/cli.py", "src/log_tool/registry.py", "src/log_tool/commands/scan.py",
                  "src/log_tool/commands/report.py", "config/default.toml", "tests/test_cli.py", "docs/ARCHITECTURE.md"):
            self.assertIn(f, rec["written"])
        self.assertTrue(all(v["ok"] for v in rec["validation"]))
        proj = tomllib.loads(self.text("pyproject.toml"))["project"]
        self.assertEqual(proj["scripts"], {"log-tool": "log_tool.cli:main"})
        self.assertEqual(proj["description"], 'Scans "logs" and more')
        self.assertEqual(rec["dependency_analysis"]["python"]["undeclared"], [])
        self.assertIn("from . import scan\nfrom . import report", self.text("src/log_tool/commands/__init__.py"))

    def test_package_name_never_shadows_stdlib(self):
        self.assertEqual(safe_pkg("Logging"), "app_logging")
        self.assertEqual(safe_pkg("9 Lives"), "app_9_lives")
        rec = self.gen.compose(self.pid, "python_software", {**PY, "project_name": "Json"})
        self.assertTrue(any(f.startswith("src/app_json/") for f in rec["written"]))

    def test_generated_tests_cover_each_command(self):
        self.gen.compose(self.pid, "python_software", PY)
        names = {n.name for n in ast.walk(ast.parse(self.text("tests/test_cli.py"))) if isinstance(n, ast.FunctionDef)}
        self.assertTrue({"test_scan", "test_report_upper", "test_unknown_command_exits", "test_all_commands_registered"} <= names)


class TestMobile(CreatorBase):
    def test_rejections(self):
        for bad in ({"screens": []}, {"screens": [{"name": "a", "kind": "list"}]}, {"screens": [{"name": "a", "kind": "form"}]},
                    {"screens": [{"name": "a", "kind": "video"}]}, {"screens": [{"name": "a"}, {"name": "a"}]},
                    {"theme": {"primary": "blue"}}, {"screens": [{"name": "A"}]}):
            with self.assertRaises(SpecError, msg=str(bad)):
                norm_mobile({**MOBILE, **bad})

    def test_generation(self):
        rec = self.gen.compose(self.pid, "mobile_app", MOBILE)
        for f in ("App.js", "app.json", "package.json", "src/data/content.js", "src/components/FormScreen.js",
                  "assets/manifest.json", "__tests__/content.test.js"):
            self.assertIn(f, rec["written"])
        self.assertTrue(all(v["ok"] for v in rec["validation"]))
        self.assertEqual(rec["dependency_analysis"]["javascript"]["undeclared"], [])
        self.assertEqual(json.loads(self.text("package.json"))["main"], "App.js")
        self.assertNotIn("</script>", self.text("src/data/content.js"))
        self.assertIn("toHaveLength(3)", self.text("__tests__/content.test.js"))


class TestGame(CreatorBase):
    def test_rejections(self):
        for bad in ({"width": 10}, {"lives": 0}, {"hazards": 99}, {"seed": -1}, {"width": True}, {"width": "640"},
                    {"colors": {"player": "green"}}, {"unknown": 1}):
            with self.assertRaises(SpecError, msg=str(bad)):
                norm_game({**GAME, **bad})

    def test_generation(self):
        rec = self.gen.compose(self.pid, "game_collector", GAME)
        for f in ("src/star_grab/logic.py", "src/star_grab/main.py", "config/game.json", "tests/test_logic.py",
                  "assets/images/player.svg", "assets/manifest.json", "docs/DESIGN.md"):
            self.assertIn(f, rec["written"])
        self.assertTrue(all(v["ok"] for v in rec["validation"]))
        self.assertEqual(rec["dependency_analysis"]["python"]["undeclared"], [])
        cfg = json.loads(self.text("config/game.json"))
        self.assertEqual((cfg["hazards"], cfg["lives"], cfg["seed"]), (2, 3, 42))
        manifest = json.loads(self.text("assets/manifest.json"))
        for asset in manifest["images"]:
            self.assertIn(asset, self.user_files())

    def test_logic_structure_and_purity(self):
        self.gen.compose(self.pid, "game_collector", GAME)
        tree = ast.parse(self.text("src/star_grab/logic.py"))
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn("pygame", imports)  # pure logic stays testable
        self.assertTrue({"new_game", "step"} <= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)})
        tests = {n.name for n in ast.walk(ast.parse(self.text("tests/test_logic.py"))) if isinstance(n, ast.FunctionDef)}
        self.assertIn("test_hazard_costs_a_life", tests)

    def test_no_hazard_tests_when_no_hazards(self):
        self.gen.compose(self.pid, "game_collector", {**GAME, "hazards": 0})
        self.assertNotIn("test_hazard_costs_a_life", self.text("tests/test_logic.py"))

    def test_reproducible_across_projects(self):
        p2 = self.ws.create_project("b")
        self.assertEqual(self.gen.compose(self.pid, "game_collector", GAME)["content_digest"],
                         self.gen.compose(p2, "game_collector", GAME)["content_digest"])


class TestSvgValidation(unittest.TestCase):
    def test_svg(self):
        ok = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
        self.assertTrue(validate_content("a.svg", ok).ok)
        for bad in ("<svg><rect></svg>", "<html/>", '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>',
                    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>'):
            self.assertFalse(validate_content("a.svg", bad).ok, bad)


class TestComposerAudit(CreatorBase):
    def test_every_composer_record_verifies(self):
        from jarvis.tests.test_creator_c4 import SPEC as SITE
        cases = {"website": SITE, "fastapi_service": API, "python_software": PY, "mobile_app": MOBILE,
                 "game_collector": GAME}
        for cid, spec in cases.items():
            pid = self.ws.create_project("v")
            self.gen.compose(pid, cid, spec)
            name = self.ws.list_control_records(pid, "generations")[0]
            self.assertEqual(self.gen.verify_generation(pid, name)["ok"], True, cid)

    def test_bad_specs_write_nothing(self):
        for cid, spec in (("fastapi_service", {"project_name": "x", "entities": [{"name": "drop", "fields": [{"name": "a"}]}]}),
                          ("python_software", {"project_name": "x", "commands": []}),
                          ("mobile_app", {"app_name": "x", "screens": []}),
                          ("game_collector", {"game_name": "x", "width": 1})):
            with self.assertRaises(GenerationError):
                self.gen.compose(self.pid, cid, spec)
        self.assertEqual(self.user_files(), [])
        self.assertEqual(len([r for r in self.audit.records(self.pid) if r["outcome"] == "rejected"]), 4)

    def test_all_composers_registered_as_scaffold_only(self):
        for c in self.gen.composers.list():
            self.assertEqual(c["support_level"], "scaffold")
        self.assertEqual(len(self.gen.composers.list()), 5)


if __name__ == "__main__":
    unittest.main()
