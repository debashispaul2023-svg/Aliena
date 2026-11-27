"""CLI tests (unittest). Run by you with PYTHONPATH=src; never run by Aliena."""
import contextlib
import io
import unittest

from log_scanner.cli import main
from log_scanner.registry import commands


class TestCli(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    def test_all_commands_registered(self):
        self.assertEqual(sorted(commands()), ['info', 'run'])

    def test_run(self):
        code, out = self.run_cli('run', '--text', 'hi')
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), '[run] hi')

    def test_run_upper(self):
        code, out = self.run_cli('run', '--text', 'hi', '--upper')
        self.assertEqual(out.strip(), '[run] hi'.upper())

    def test_info(self):
        code, out = self.run_cli('info', '--text', 'hi')
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), '[info] hi')

    def test_info_upper(self):
        code, out = self.run_cli('info', '--text', 'hi', '--upper')
        self.assertEqual(out.strip(), '[info] hi'.upper())

    def test_unknown_command_exits(self):
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                main(['nope'])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
