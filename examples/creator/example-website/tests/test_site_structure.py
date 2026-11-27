"""Structure checks for the generated site. Run by you (e.g. python -m unittest); never run by Aliena."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ['index.html', 'about.html', 'menu.html', 'faq.html', 'contact.html']


class TestSiteStructure(unittest.TestCase):
    def test_pages_exist(self):
        for page in PAGES:
            self.assertTrue((ROOT / page).is_file(), page)

    def test_local_references_resolve(self):
        for page in PAGES:
            text = (ROOT / page).read_text(encoding="utf-8")
            for ref in re.findall(r'(?:href|src)="([^"#:]+)"', text):
                self.assertTrue((ROOT / ref).exists(), f"{page} -> {ref}")


if __name__ == "__main__":
    unittest.main()
