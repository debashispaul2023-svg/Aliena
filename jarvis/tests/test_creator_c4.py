"""C4 website composer tests."""

import unittest
from html.parser import HTMLParser

from jarvis.creator.compose_website import normalize
from jarvis.creator.codegen_manager import GenerationError
from jarvis.creator.spec_utils import SpecError
from jarvis.creator.workspace_manager import CollisionError
from jarvis.tests.creator_testkit import CreatorBase

HOSTILE = "We love </script><img src=x onerror=alert(1)> \"coffee\" & 'tea'"
SPEC = {
    "site_name": "Joe's Cafe", "tagline": 'Best "coffee" in <town>', "theme": {"primary": "#112233"},
    "sections": [
        {"type": "about", "title": "About us", "text": HOSTILE},
        {"type": "services", "title": "Services", "items": [{"title": "Catering", "text": "Events"}]},
        {"type": "menu", "title": "Menu", "items": [{"title": "Latte", "text": "Milk & espresso", "price": "$4"}]},
        {"type": "gallery", "title": "Gallery", "items": [{"title": "Shop"}]},
        {"type": "testimonials", "title": "Reviews", "items": [{"title": "Ann", "text": "Great"}]},
        {"type": "faq", "title": "FAQ", "items": [{"title": "Open?", "text": "Daily"}]},
        {"type": "contact", "title": "Contact", "text": "Write us"},
    ],
    "api": {"enabled": True},
}


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attrs, self.ids, self.refs = [], set(), set(), []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for k, v in attrs:
            self.attrs.add(k)
            if k == "id":
                self.ids.add(v)
            if k in ("href", "src") and v:
                self.refs.append(v)

    handle_startendtag = handle_starttag


def parse(text):
    p = Tags()
    p.feed(text)
    return p


class TestSpec(unittest.TestCase):
    def bad(self, **kw):
        spec = {**SPEC, **kw}
        with self.assertRaises(SpecError, msg=str(kw)[:80]):
            normalize(spec)

    def test_rejections(self):
        self.bad(site_name="")
        self.bad(site_name="x" * 100)
        self.bad(framework="angular")
        self.bad(layout="multi_page", framework="react")
        self.bad(theme={"primary": "#112233;}</style>"})
        self.bad(theme={"primary": "red"})
        self.bad(theme={"bogus": 1})
        self.bad(sections=[])
        self.bad(sections=[{"type": "about"}] * 2)
        self.bad(sections=[{"type": "nope"}])
        self.bad(sections=[{"type": "menu", "items": []}])
        self.bad(sections=[{"type": "about", "extra": 1}])
        self.bad(sections=[{"type": "about", "title": "a\x00b"}])
        self.bad(sections=[{"type": "faq", "items": [{"title": "t"}] * 20}])
        self.bad(unknown_key=1)
        with self.assertRaises(SpecError):
            normalize("not a dict")

    def test_defaults(self):
        n = normalize({"site_name": "A", "sections": [{"type": "about"}]})
        self.assertEqual(n["framework"], "html")
        self.assertEqual(n["layout"], "multi_page")
        self.assertFalse(n["contact_form"])
        self.assertFalse(n["api"]["enabled"])

    def test_api_requires_contact(self):
        n = normalize({"site_name": "A", "sections": [{"type": "about"}], "api": {"enabled": True}})
        self.assertFalse(n["api"]["enabled"])


class TestHtmlSite(CreatorBase):
    def gen_site(self, **kw):
        return self.gen.compose(self.pid, "website", {**SPEC, **kw})

    def test_multi_page_site(self):
        rec = self.gen_site()
        files = set(rec["written"])
        for f in ("index.html", "about.html", "menu.html", "contact.html", "faq.html", "css/styles.css", "js/main.js",
                  "js/api.js", "assets/logo.svg", "assets/placeholder.svg", "api/openapi.yaml", "db/schema.sql",
                  "README.md", "tests/test_site_structure.py"):
            self.assertIn(f, files)
        self.assertTrue(all(v["ok"] for v in rec["validation"]))
        self.assertEqual(rec["dependency_analysis"]["python"]["undeclared"], [])
        self.assertEqual(self.ws.verify_integrity(self.pid)["ok"], True)

    def test_hostile_text_is_escaped(self):
        self.gen_site()
        for page in [f for f in self.user_files() if f.endswith(".html")]:
            p = parse(self.text(page))
            self.assertNotIn("onerror", p.attrs, page)
            self.assertEqual(p.tags.count("script"), len([r for r in p.refs if r.startswith("js/")]), page)
            self.assertNotIn("<img src=x", self.text(page))
        self.assertIn("&lt;/script&gt;", self.text("about.html"))
        self.assertIn("Joe&#x27;s Cafe", self.text("index.html"))

    def test_internal_links_and_assets_resolve(self):
        self.gen_site()
        for page in [f for f in self.user_files() if f.endswith(".html")]:
            for ref in parse(self.text(page)).refs:
                if ref.startswith(("#", "http")):
                    continue
                self.assertIn(ref, self.user_files(), f"{page} -> {ref}")

    def test_responsive_accessible_structure(self):
        self.gen_site()
        css = self.text("css/styles.css")
        self.assertIn("@media (min-width", css)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn("#112233", css)
        html = self.text("contact.html")
        self.assertIn('<html lang="en">', html)
        self.assertIn('name="viewport"', html)
        self.assertIn("skip-link", html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('role="status"', html)
        self.assertEqual(html.count("<label>"), 3)

    def test_no_dark_mode_option(self):
        self.gen_site(theme={"primary": "#112233", "dark_mode": False})
        self.assertNotIn("prefers-color-scheme: dark", self.text("css/styles.css"))

    def test_single_page_anchors(self):
        self.gen_site(layout="single_page")
        p = parse(self.text("index.html"))
        self.assertEqual({"about", "menu", "contact"} <= p.ids, True)
        anchors = {r[1:] for r in p.refs if r.startswith("#") and len(r) > 1}
        self.assertTrue(anchors <= p.ids | {"main", "top"}, anchors - p.ids)
        self.assertNotIn("about.html", self.user_files())

    def test_api_files_only_when_enabled(self):
        self.gen_site(api={"enabled": False})
        files = self.user_files()
        for f in ("js/api.js", "api/openapi.yaml", "db/schema.sql"):
            self.assertNotIn(f, files)
        self.assertNotIn("/api/contact", self.text("js/main.js"))

    def test_generated_test_file_is_valid_python_and_not_run(self):
        self.gen_site()
        import ast
        ast.parse(self.text("tests/test_site_structure.py"))
        self.assertFalse(list(self.pdir().rglob("__pycache__")))

    def test_json_data_never_contains_raw_angle_brackets(self):
        self.gen_site(framework="react", layout="single_page")
        data = self.text("src/siteData.js")
        self.assertNotIn("</script>", data)
        self.assertNotIn("<img", data)
        self.assertIn("\\u003c", data)


class TestReactNext(CreatorBase):
    def run_fw(self, fw):
        return self.gen.compose(self.pid, "website", {**SPEC, "framework": fw, "layout": "single_page"})

    def test_react(self):
        rec = self.run_fw("react")
        for f in ("package.json", "vite.config.js", "src/App.jsx", "src/main.jsx", "src/siteData.js",
                  "src/components/ContactForm.jsx", "src/components/Navbar.jsx", "src/styles.css"):
            self.assertIn(f, rec["written"])
        self.assertEqual(rec["dependency_analysis"]["javascript"]["undeclared"], [])
        self.assertIn("react-dom", rec["dependency_analysis"]["javascript"]["declared"])
        self.assertTrue(all(v["ok"] for v in rec["validation"]))
        self.assertNotIn("dangerouslySetInnerHTML", "".join(self.text(f) for f in self.user_files()))

    def test_next(self):
        rec = self.run_fw("nextjs")
        for f in ("app/layout.js", "app/page.js", "lib/siteData.js", "components/ContactForm.jsx", "next.config.js"):
            self.assertIn(f, rec["written"])
        self.assertTrue(self.text("components/ContactForm.jsx").startswith("'use client';"))
        self.assertTrue(self.text("components/Navbar.jsx").startswith("'use client';"))
        self.assertEqual(rec["dependency_analysis"]["javascript"]["undeclared"], [])
        self.assertTrue(all(v["ok"] for v in rec["validation"]))

    def test_package_json_name_is_slug(self):
        self.run_fw("react")
        import json
        self.assertEqual(json.loads(self.text("package.json"))["name"], "joe-s-cafe")


class TestComposerSafety(CreatorBase):
    def test_reproducible_and_verifiable(self):
        p2 = self.ws.create_project("b")
        a = self.gen.compose(self.pid, "website", SPEC)
        b = self.gen.compose(p2, "website", SPEC)
        self.assertEqual(a["content_digest"], b["content_digest"])
        name = self.ws.list_control_records(self.pid, "generations")[0]
        self.assertEqual(self.gen.verify_generation(self.pid, name)["ok"], True)
        self.assertEqual(a["generator_kind"], "composer")
        self.assertFalse(a["executed"])

    def test_invalid_spec_writes_nothing_and_is_audited(self):
        with self.assertRaises(GenerationError):
            self.gen.compose(self.pid, "website", {**SPEC, "theme": {"primary": "javascript:x"}})
        self.assertEqual(self.user_files(), [])
        self.assertTrue(any(r["outcome"] == "rejected" for r in self.audit.records(self.pid)))

    def test_unknown_composer(self):
        with self.assertRaises(GenerationError):
            self.gen.compose(self.pid, "nope", SPEC)

    def test_collision_protection(self):
        self.gen.compose(self.pid, "website", SPEC)
        with self.assertRaises(CollisionError):
            self.gen.compose(self.pid, "website", SPEC)

    def test_all_paths_inside_workspace(self):
        for fw in ("html", "react", "nextjs"):
            pid = self.ws.create_project("p")
            rec = self.gen.compose(pid, "website", {**SPEC, "framework": fw,
                                                    **({"layout": "single_page"} if fw != "html" else {})})
            for f in rec["written"]:
                self.assertFalse(f.startswith(("/", "..")) or ".." in f.split("/"), f)


if __name__ == "__main__":
    unittest.main()
