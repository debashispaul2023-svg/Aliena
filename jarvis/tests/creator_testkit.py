"""Shared helpers for Creator tests (not a test module)."""

import tempfile
import unittest
from pathlib import Path

from jarvis.core.approval import ApprovalDecision
from jarvis.creator import AuditLogger, CodeGenerationManager, CreatorWorkspaceManager, SecurityGate


def ok(action):
    return ApprovalDecision(action=action, approved=True, reviewer="user")


class CreatorBase(unittest.TestCase):
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

    def text(self, rel, pid=None):
        return (self.pdir(pid) / rel).read_text(encoding="utf-8")
