"""C8 (static preview) and C9 (delivery) tests."""

import io
import re
import unittest
import zipfile
from pathlib import Path

from jarvis.creator import delivery_manager as dm_mod
from jarvis.creator import preview_manager as pm_mod
from jarvis.creator.delivery_manager import DeliveryManager, DeliveryRefused
from jarvis.creator.preview_manager import PreviewManager, sanitize_css
from jarvis.creator.workspace_manager import (ApprovalRequired, CollisionError, CreatorWorkspaceError)
from jarvis.tests.creator_testkit import CreatorBase, ok
from jarvis.tests.test_creator_c4 import SPEC as SITE
from jarvis.tests.test_creator_c5_c6 import API, GAME, MOBILE, PY


def attrs_of(text):
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.names = []

        def handle_starttag(self, tag, attrs):
            self.names += [k for k, _ in attrs]

        handle_startendtag = handle_starttag

    p = P()
    p.feed(text)
    return p.names


class PBase(CreatorBase):
    def setUp(self):
        super().setUp()
        self.pm = PreviewManager(self.ws, self.gate, self.audit)
        self.dm = DeliveryManager(self.ws, self.gate, self.audit)

    def site(self, pid=None, **kw):
        self.gen.compose(pid or self.pid, "website", {**SITE, **kw})

    def preview(self, name, pid=None):
        return self.ws.read_artifact(pid or self.pid, "preview", name).decode()


class TestPreview(PBase):
    def test_static_site_preview_is_inert_and_self_contained(self):
        self.site()
        r = self.pm.build_static_preview(self.pid)
        self.assertTrue(r["built"])
        self.assertEqual((r["mode"], r["server_started"], r["executed"]), ("static_no_script", False, False))
        self.assertEqual(sorted(f["source"] for f in r["files"]), sorted(f for f in self.user_files() if f.endswith(".html")))
        for f in r["files"]:
            h = self.preview(f["source"])
            self.assertNotIn("<script", h)
            parsed = attrs_of(h)
            self.assertFalse([a for a in parsed if a.startswith("on")], f["source"])  # real attributes only
            self.assertNotIn("<link", h)
            self.assertNotRegex(h, r'(?:src|href)="https?:')
            self.assertIn("Content-Security-Policy", h)
            self.assertIn("default-src &#x27;none&#x27;", h)
        index = self.preview("index.html")
        self.assertIn("<style>", index)
        self.assertIn("#112233", index)  # theme colour inlined from css/styles.css
        self.assertIn("data:image/svg+xml;base64,", index)
        self.assertTrue(any("<script>" in x for x in r["removed"]))

    def test_hostile_page_is_sanitised(self):
        self.ws.write_file(self.pid, "README.md", "x")
        self.ws.write_file(self.pid, "a.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.ws.write_file(self.pid, "s.css", "@import url(http://evil/x.css);\nbody{background:url(http://evil/p.png);color:red}")
        self.ws.write_file(self.pid, "index.html",
                           '<!DOCTYPE html><html><head><link rel="stylesheet" href="s.css"><link rel="stylesheet" href="https://evil/x.css">'
                           '<base href="https://evil/"></head><body onload="x()"><script>alert(1)</script>'
                           '<img src="a.svg" onerror="alert(2)"><img src="https://evil/t.png">'
                           '<iframe src="https://evil"></iframe><object data="x"></object>'
                           '<form action="https://evil/post"><input></form><p style="background:url(http://evil/z)">hi &amp; bye</p></body></html>')
        r = self.pm.build_static_preview(self.pid)
        self.assertTrue(r["built"], r)
        h = self.preview("index.html")
        for bad in ("alert", "evil", "onload", "onerror", "<iframe", "<object", "<base", "@import", "action="):
            self.assertNotIn(bad, h, bad)
        self.assertIn("color:red", h)
        self.assertIn("hi &amp; bye", h)
        self.assertIn("data:image/svg+xml", h)

    def test_javascript_url_refuses_preview(self):
        self.ws.write_file(self.pid, "README.md", "x")
        self.ws.write_file(self.pid, "index.html", '<a href="javascript:alert(1)">x</a>')
        r = self.pm.build_static_preview(self.pid)
        self.assertFalse(r["built"])
        self.assertTrue(r["refused"])
        self.assertEqual(self.ws.list_artifacts(self.pid, "preview"), [])

    def test_broken_reference_refuses_preview(self):
        self.ws.write_file(self.pid, "README.md", "x")
        self.ws.write_file(self.pid, "index.html", '<img src="missing.png">')
        self.assertFalse(self.pm.build_static_preview(self.pid)["built"])

    def test_execution_requiring_projects_are_blocked(self):
        cases = {"fastapi_service": API, "python_software": PY, "mobile_app": MOBILE, "game_collector": GAME}
        for cid, spec in cases.items():
            pid = self.ws.create_project("b")
            self.gen.compose(pid, cid, spec)
            r = self.pm.build_static_preview(pid)
            self.assertEqual((r["supported"], r["built"], r["mode"], r["executed"], r["server_started"]), (False, False, "blocked", False, False), cid)
            self.assertIn("BLOCKED", r["reason"])
            self.assertEqual(self.ws.list_artifacts(pid, "preview"), [])
        react = self.ws.create_project("r")
        self.gen.compose(react, "website", {**SITE, "framework": "react", "layout": "single_page"})
        self.assertFalse(self.pm.build_static_preview(react)["built"])
        self.assertTrue(any(r["action"] == "preview" and r["outcome"] == "blocked" for r in self.audit.records(react)))

    def test_rebuild_removes_stale_preview_and_keeps_project_clean(self):
        self.site()
        self.pm.build_static_preview(self.pid)
        self.ws.write_file(self.pid, "extra.html", "<p>x</p>")
        self.pm.build_static_preview(self.pid)
        self.assertIn("extra.html", self.ws.list_artifacts(self.pid, "preview"))
        self.assertTrue(self.ws.verify_integrity(self.pid)["ok"])
        self.assertEqual(self.ws.verify_integrity(self.pid)["untracked"], [])
        self.assertTrue(all(not f.startswith(".creator") for f in self.user_files()))

    def test_preview_audited(self):
        self.site()
        self.pm.build_static_preview(self.pid)
        self.assertTrue(any(r["action"] == "preview" and r["outcome"] == "built" for r in self.audit.records(self.pid)))

    def test_sanitize_css(self):
        out = sanitize_css('@import "a.css";@import url(x);a{background:url( https://e/x ) ;b:url(data:image/png;base64,AAA)}')
        self.assertNotIn("@import", out)
        self.assertNotIn("https://e", out)
        self.assertIn("data:image/png;base64,AAA", out)


class TestArtifactStorage(PBase):
    def test_names_and_kinds_validated(self):
        for kind, name in (("preview", "../x"), ("preview", ".hidden"), ("preview", "a/b"), ("nope", "a"), ("deliveries", ""), ("preview", "x" * 200)):
            with self.assertRaises(CreatorWorkspaceError, msg=(kind, name)):
                self.ws.write_artifact(self.pid, kind, name, b"x")

    def test_deliveries_never_overwritten_or_cleared(self):
        self.ws.write_artifact(self.pid, "deliveries", "a.zip", b"1")
        with self.assertRaises(CollisionError):
            self.ws.write_artifact(self.pid, "deliveries", "a.zip", b"2", overwrite=True)
        with self.assertRaises(ApprovalRequired):
            self.ws.clear_artifacts(self.pid, "deliveries")
        self.assertEqual(self.ws.read_artifact(self.pid, "deliveries", "a.zip"), b"1")


class TestDelivery(PBase):
    def package_site(self):
        self.site()
        return self.dm.package(self.pid)

    def test_package_contents_and_evidence(self):
        rec = self.package_site()
        self.assertEqual(rec["version"], 1)
        self.assertEqual((rec["status"], rec["runtime_verified"], rec["published"], rec["deployed"]),
                         ("delivered_static_verified", False, False, False))
        data = self.ws.read_artifact(self.pid, "deliveries", "demo-v1.zip")
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        self.assertTrue(all(n.startswith("demo/") for n in names))
        self.assertFalse(any(".creator" in n for n in names))
        for tracked in self.ws.manifest(self.pid):
            self.assertIn(f"demo/{tracked}", names)
        for meta in ("BUILD_REPORT.json", "TEST_REPORT.json", "DELIVERY.md", "MANIFEST.sha256"):
            self.assertIn(f"demo/_aliena/{meta}", names)
        import json
        build = json.loads(zf.read("demo/_aliena/BUILD_REPORT.json"))
        test = json.loads(zf.read("demo/_aliena/TEST_REPORT.json"))
        self.assertFalse(build["runtime_verified"])
        self.assertEqual(build["generations"][0]["generator"], "website")
        self.assertEqual(test["categories"]["runtime_tests"]["status"], "blocked")
        self.assertNotIn("created_at", test)
        self.assertIn("NOT executed", zf.read("demo/_aliena/DELIVERY.md").decode())
        self.assertEqual(zf.testzip(), None)

    def test_untracked_user_files_excluded_but_reported(self):
        self.site()
        (self.pdir() / "private-notes.txt").write_text("mine")
        self.dm.package(self.pid)
        zf = zipfile.ZipFile(io.BytesIO(self.ws.read_artifact(self.pid, "deliveries", "demo-v1.zip")))
        self.assertFalse(any("private-notes" in n for n in zf.namelist()))
        import json
        self.assertEqual(json.loads(zf.read("demo/_aliena/BUILD_REPORT.json"))["excluded_untracked_files"], ["private-notes.txt"])

    def test_versioned_deterministic_and_checkpointed(self):
        self.site()
        r1, r2 = self.dm.package(self.pid), self.dm.package(self.pid)
        self.assertEqual((r1["version"], r2["version"]), (1, 2))
        self.assertEqual(r1["zip_sha256"], r2["zip_sha256"])  # same state => byte-identical ZIP
        self.assertEqual(self.ws.list_artifacts(self.pid, "deliveries"), ["demo-v1.zip", "demo-v2.zip"])  # previous kept
        self.assertNotEqual(r1["checkpoint"], r2["checkpoint"])
        for info in zipfile.ZipFile(io.BytesIO(self.ws.read_artifact(self.pid, "deliveries", "demo-v1.zip"))).infolist():
            self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))

    def test_every_composer_output_is_deliverable_and_verifies(self):
        cases = {"website": SITE, "fastapi_service": API, "python_software": PY, "mobile_app": MOBILE, "game_collector": GAME}
        for cid, spec in cases.items():
            pid = self.ws.create_project("e2e")
            self.gen.compose(pid, cid, spec)
            self.dm.package(pid)
            self.assertTrue(self.dm.verify_delivery(pid, 1)["ok"], cid)

    def test_refusals(self):
        empty = self.ws.create_project("empty")
        with self.assertRaises(DeliveryRefused):
            self.dm.package(empty)
        self.ws.write_file(self.pid, "README.md", "x")
        self.ws.write_file(self.pid, "bad.py", "def (:\n")
        with self.assertRaises(DeliveryRefused) as cm:
            self.dm.package(self.pid)
        self.assertIn("failed: syntax", cm.exception.reasons)
        p3 = self.ws.create_project("tampered")
        self.site(p3)
        (self.pdir(p3) / "index.html").write_text("tampered")
        with self.assertRaises(DeliveryRefused):
            self.dm.package(p3)
        p4 = self.ws.create_project("secret")
        self.site(p4)
        self.ws.write_file(p4, "keys.txt", "k=sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345\n")
        with self.assertRaises(DeliveryRefused):
            self.dm.package(p4)
        p5 = self.ws.create_project("reserved")
        self.ws.write_file(p5, "README.md", "x")
        self.ws.write_file(p5, "_aliena/x.txt", "x")
        with self.assertRaises(DeliveryRefused):
            self.dm.package(p5)
        for p in (empty, self.pid, p3, p4, p5):
            self.assertEqual(self.ws.list_artifacts(p, "deliveries"), [])
        self.assertTrue(any(r["action"] == "delivery" and r["outcome"] == "refused" for r in self.audit.records(p3)))

    def test_verify_detects_tampering(self):
        self.package_site()
        self.assertTrue(self.dm.verify_delivery(self.pid, 1)["ok"])
        path = self.pdir() / ".creator" / "deliveries" / "demo-v1.zip"
        src = zipfile.ZipFile(io.BytesIO(path.read_bytes()))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for n in src.namelist():
                zf.writestr(n, b"HACKED" if n == "demo/README.md" else src.read(n))
            zf.writestr("demo/extra.txt", b"x")
        path.write_bytes(out.getvalue())
        v = self.dm.verify_delivery(self.pid, 1)
        self.assertFalse(v["ok"])
        self.assertIn("demo/README.md", v["mismatch"])
        self.assertIn("<zip file hash>", v["mismatch"])
        self.assertIn("demo/extra.txt", v["unexpected"])

    def test_zip_entry_names_are_safe(self):
        self.package_site()
        for n in zipfile.ZipFile(io.BytesIO(self.ws.read_artifact(self.pid, "deliveries", "demo-v1.zip"))).namelist():
            self.assertFalse(n.startswith("/") or ".." in n.split("/") or "\\" in n, n)

    def test_export_requires_exact_approval_and_outside_destination(self):
        self.package_site()
        out = Path(self._tmp.name) / "out"
        out.mkdir()
        with self.assertRaises(ApprovalRequired):
            self.dm.export(self.pid, 1, str(out))
        with self.assertRaises(ApprovalRequired):
            self.dm.export(self.pid, 1, str(out), approval=ok("publish"))
        self.assertEqual(list(out.iterdir()), [])
        with self.assertRaises(CreatorWorkspaceError):
            self.dm.export(self.pid, 1, str(self.root), approval=ok("export_delivery"))
        with self.assertRaises(CreatorWorkspaceError):
            self.dm.export(self.pid, 1, str(out / "missing"), approval=ok("export_delivery"))
        target = self.dm.export(self.pid, 1, str(out), approval=ok("export_delivery"))
        self.assertEqual(Path(target).read_bytes(), self.ws.read_artifact(self.pid, "deliveries", "demo-v1.zip"))
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["demo-v1.zip"])  # no temp files
        with self.assertRaises(CollisionError):
            self.dm.export(self.pid, 1, str(out), approval=ok("export_delivery"))
        self.assertTrue(any(r["action"] == "export_delivery" and r["outcome"] == "denied" for r in self.audit.records(self.pid)))

    def test_delivery_audited_and_chain_valid(self):
        self.package_site()
        acts = {(r["action"], r["outcome"]) for r in self.audit.records(self.pid)}
        self.assertIn(("delivery", "ok"), acts)
        self.assertIn(("execute_code", "denied"), acts)
        self.assertTrue(self.audit.verify_chain())


class TestNoExecutionPrimitives(unittest.TestCase):
    def test_sources(self):
        banned = ("subprocess", "os.system", "os.popen", "eval(", "exec(", "shell=True", "import socket", "importlib",
                  "__import__", "runpy", "http.server", "webbrowser", "urllib")
        for mod in (pm_mod, dm_mod):
            src = Path(mod.__file__).read_text()
            for b in banned:
                self.assertNotIn(b, src, f"{b} in {mod.__name__}")
            self.assertIsNone(re.search(r"(?<![\w.])compile\(", src))


if __name__ == "__main__":
    unittest.main()
