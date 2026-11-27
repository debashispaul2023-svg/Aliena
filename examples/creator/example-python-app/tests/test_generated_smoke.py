"""Generated smoke test: every module compiles and the README exists. Run by you; never run by Aliena."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ['src/log_scanner/__main__.py', 'src/log_scanner/cli.py', 'src/log_scanner/commands/info.py', 'src/log_scanner/commands/run.py', 'src/log_scanner/config.py', 'src/log_scanner/logging_setup.py', 'src/log_scanner/registry.py']


class TestSmoke(unittest.TestCase):
    def test_modules_parse(self):
        for rel in MODULES:
            source = (ROOT / rel).read_text(encoding="utf-8")
            ast.parse(source, filename=rel)

    def test_readme_exists(self):
        self.assertTrue(any(p.name.lower().startswith("readme") for p in ROOT.iterdir()))


if __name__ == "__main__":
    unittest.main()
