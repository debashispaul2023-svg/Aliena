"""The shipped example projects are intact, self-consistent and honest about verification."""

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "examples" / "creator"


class TestExamples(unittest.TestCase):
    def test_examples_present_and_manifest_matches_files(self):
        for name in ("example-website", "example-python-app"):
            base = ROOT / name
            self.assertTrue(base.is_dir(), name)
            manifest = (base / "_aliena" / "MANIFEST.sha256").read_text().splitlines()
            self.assertGreater(len(manifest), 10)
            for line in manifest:
                digest, _, rel = line.partition("  ")
                inner = rel.split("/", 1)[1]  # strip project root folder
                if inner.endswith("MANIFEST.sha256"):
                    continue
                self.assertEqual(hashlib.sha256((base / inner).read_bytes()).hexdigest(), digest, f"{name}/{inner}")

    def test_examples_state_limitations_honestly(self):
        for name in ("example-website", "example-python-app"):
            build = json.loads((ROOT / name / "_aliena" / "BUILD_REPORT.json").read_text())
            test = json.loads((ROOT / name / "_aliena" / "TEST_REPORT.json").read_text())
            self.assertFalse(build["runtime_verified"])
            self.assertEqual(test["completion"]["status"], "static_verified_runtime_unverified")
            self.assertEqual(test["categories"]["runtime_tests"]["status"], "blocked")
            self.assertEqual(test["commands_executed"], [])
            self.assertIn("NOT executed", (ROOT / name / "_aliena" / "DELIVERY.md").read_text())

    def test_website_example_has_pages_and_python_example_has_package(self):
        site = ROOT / "example-website"
        for page in ("index.html", "menu.html", "about.html", "faq.html", "contact.html", "css/styles.css"):
            self.assertTrue((site / page).is_file(), page)
        self.assertIn("Sunrise Bakery", (site / "index.html").read_text())
        app = ROOT / "example-python-app"
        self.assertTrue((app / "src" / "log_scanner" / "cli.py").is_file())
        self.assertTrue((app / "tests" / "test_cli.py").is_file())


if __name__ == "__main__":
    unittest.main()
