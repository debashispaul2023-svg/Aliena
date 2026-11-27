"""Creator Engine C2 tests: workspace isolation, path safety, atomicity, rollback."""

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core.approval import ApprovalDecision
from jarvis.creator import AuditLogger, SecurityGate
from jarvis.creator import workspace_manager as wm
from jarvis.creator.workspace_manager import (ApprovalRequired, CollisionError, CreatorWorkspaceError,
                                              CreatorWorkspaceManager, PathViolation, UnknownProject)


def ok(action):
    return ApprovalDecision(action=action, approved=True, reviewer="user")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "ws"
        self.audit = AuditLogger()
        self.mgr = CreatorWorkspaceManager(self.root, SecurityGate(self.audit), self.audit)
        self.pid = self.mgr.create_project("demo", "static_website")

    def tearDown(self):
        self._tmp.cleanup()

    def pdir(self, pid=None):
        return self.root / (pid or self.pid)


class TestProject(Base):
    def test_unique_ids_and_metadata(self):
        p2 = self.mgr.create_project("demo")
        self.assertNotEqual(self.pid, p2)
        self.assertTrue(re.match(r"^cre_[0-9a-f]{16}$", self.pid))
        meta = self.mgr.metadata(self.pid)
        self.assertEqual(meta["name"], "demo")
        self.assertEqual(meta["project_type"], "static_website")
        self.assertEqual(self.mgr.list_projects(), sorted([self.pid, p2]))

    def test_bad_project_name(self):
        for bad in ("", "../x", "a/b", "..", ".hidden"):
            with self.assertRaises(Exception):
                self.mgr.create_project(bad)

    def test_manifest_inventory_history(self):
        self.mgr.write_file(self.pid, "src/index.html", "<h1>hi</h1>")
        inv = self.mgr.inventory(self.pid)
        self.assertEqual(inv[0]["path"], "src/index.html")
        self.assertEqual(inv[0]["origin"], "generated")
        self.assertEqual(len(inv[0]["sha256"]), 64)
        self.assertEqual([h["action"] for h in self.mgr.history(self.pid)], ["create_project", "write_file"])
        self.assertEqual(self.mgr.read_file(self.pid, "src/index.html"), b"<h1>hi</h1>")


class TestPathSafety(Base):
    BAD = ["../escape.txt", "a/../../escape.txt", "/etc/passwd", "C:/x.txt", "C:\\x.txt", "..\\x.txt",
           "a//b.txt", "./a.txt", "", "a\x00b", ".creator/project.json", ".CREATOR/x", "nul.txt",
           "dir/con", "~/x", "trail.", " lead.txt", "a:b", ".env", "x" * 300]

    def test_traversal_variants_rejected_and_audited(self):
        for bad in self.BAD:
            with self.assertRaises(PathViolation, msg=repr(bad)):
                self.mgr.write_file(self.pid, bad, "x")
        denied = [r for r in self.audit.records(self.pid) if r["action"] == "workspace_escape"]
        self.assertGreaterEqual(len(denied), len(self.BAD))
        self.assertTrue(all(r["outcome"] == "denied" for r in denied))
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_symlink_escape_blocked(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        os.symlink(outside, self.pdir() / "link")
        with self.assertRaises(PathViolation):
            self.mgr.write_file(self.pid, "link/pwn.txt", "x")
        self.assertFalse((outside / "pwn.txt").exists())

    def test_symlinked_file_blocked(self):
        victim = Path(self._tmp.name) / "victim.txt"
        victim.write_text("keep")
        os.symlink(victim, self.pdir() / "f.txt")
        with self.assertRaises(PathViolation):
            self.mgr.write_file(self.pid, "f.txt", "x", overwrite=True, approval=ok("overwrite_file"))
        self.assertEqual(victim.read_text(), "keep")

    def test_invalid_project_ids(self):
        for bad in ("../ws", "cre_" + "0" * 16, "", None, "cre_../../x"):
            with self.assertRaises(UnknownProject):
                self.mgr.write_file(bad, "a.txt", "x")

    def test_size_limit(self):
        with self.assertRaises(CreatorWorkspaceError):
            self.mgr.write_file(self.pid, "big.bin", b"x" * (wm.MAX_FILE_BYTES + 1))


class TestCollisions(Base):
    def test_existing_generated_file_not_overwritten(self):
        self.mgr.write_file(self.pid, "a.txt", "one")
        with self.assertRaises(CollisionError):
            self.mgr.write_file(self.pid, "a.txt", "two")
        self.assertEqual(self.mgr.read_file(self.pid, "a.txt"), b"one")

    def test_user_owned_file_protected(self):
        (self.pdir() / "mine.txt").write_text("user data")
        with self.assertRaises(CollisionError):
            self.mgr.write_file(self.pid, "mine.txt", "x")
        with self.assertRaises(ApprovalRequired):  # overwrite flag alone is not enough
            self.mgr.write_file(self.pid, "mine.txt", "x", overwrite=True)
        self.assertEqual((self.pdir() / "mine.txt").read_text(), "user data")

    def test_overwrite_needs_matching_approval_and_backs_up(self):
        self.mgr.write_file(self.pid, "a.txt", "one")
        with self.assertRaises(ApprovalRequired):
            self.mgr.write_file(self.pid, "a.txt", "two", overwrite=True, approval=ok("publish"))
        self.mgr.write_file(self.pid, "a.txt", "two", overwrite=True, approval=ok("overwrite_file"))
        self.assertEqual(self.mgr.read_file(self.pid, "a.txt"), b"two")
        backups = list((self.pdir() / ".creator" / "backups").rglob("a.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "one")

    def test_case_variant_and_dir_and_parent_file_collisions(self):
        self.mgr.write_file(self.pid, "Readme.md", "x")
        with self.assertRaises(CollisionError):
            self.mgr.write_file(self.pid, "README.md", "y")
        (self.pdir() / "d").mkdir()
        with self.assertRaises(CollisionError):
            self.mgr.write_file(self.pid, "d", "y", overwrite=True, approval=ok("overwrite_file"))
        with self.assertRaises(CollisionError):
            self.mgr.write_file(self.pid, "Readme.md/x.txt", "y")


class TestAtomicity(Base):
    def test_failed_replace_leaves_original_and_no_temp(self):
        self.mgr.write_file(self.pid, "a.txt", "orig")
        before = self.mgr.manifest(self.pid)
        with mock.patch("jarvis.creator.workspace_manager.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.mgr.write_file(self.pid, "a.txt", "new", overwrite=True, approval=ok("overwrite_file"))
        self.assertEqual((self.pdir() / "a.txt").read_text(), "orig")
        self.assertEqual(self.mgr.manifest(self.pid), before)
        self.assertEqual(list(self.pdir().rglob(".tmp_*")), [])

    def test_failed_new_file_not_recorded(self):
        with mock.patch("jarvis.creator.workspace_manager.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.mgr.write_file(self.pid, "n.txt", "x")
        self.assertFalse((self.pdir() / "n.txt").exists())
        self.assertNotIn("n.txt", self.mgr.manifest(self.pid))

    def test_integrity_detection(self):
        self.mgr.write_file(self.pid, "a.txt", "1")
        self.mgr.write_file(self.pid, "b.txt", "2")
        self.assertTrue(self.mgr.verify_integrity(self.pid)["ok"])
        (self.pdir() / "a.txt").write_text("tampered")
        (self.pdir() / "b.txt").unlink()
        (self.pdir() / "user.txt").write_text("u")
        r = self.mgr.verify_integrity(self.pid)
        self.assertEqual((r["modified"], r["missing"], r["untracked"]), (["a.txt"], ["b.txt"], ["user.txt"]))
        self.assertFalse(r["ok"])


class TestRollback(Base):
    def test_rollback_restores_and_removes(self):
        self.mgr.write_file(self.pid, "a.txt", "v1")
        cid = self.mgr.create_checkpoint(self.pid, "first")
        self.mgr.write_file(self.pid, "a.txt", "v2", overwrite=True, approval=ok("overwrite_file"))
        self.mgr.write_file(self.pid, "new.txt", "n")
        (self.pdir() / "user.txt").write_text("keep me")
        with self.assertRaises(ApprovalRequired):  # removal needs delete approval
            self.mgr.rollback(self.pid, cid)
        self.assertEqual(self.mgr.read_file(self.pid, "a.txt"), b"v2")
        res = self.mgr.rollback(self.pid, cid, approval=ok("delete_file"))
        self.assertEqual(res["restored"], ["a.txt"])
        self.assertEqual(res["removed"], ["new.txt"])
        self.assertEqual(self.mgr.read_file(self.pid, "a.txt"), b"v1")
        self.assertFalse((self.pdir() / "new.txt").exists())
        self.assertEqual((self.pdir() / "user.txt").read_text(), "keep me")
        self.assertEqual(list(self.mgr.manifest(self.pid)), ["a.txt"])
        self.assertTrue(self.mgr.verify_integrity(self.pid)["ok"])

    def test_rollback_is_undoable_via_safety_checkpoint(self):
        self.mgr.write_file(self.pid, "a.txt", "v1")
        c1 = self.mgr.create_checkpoint(self.pid)
        self.mgr.write_file(self.pid, "a.txt", "v2", overwrite=True, approval=ok("overwrite_file"))
        res = self.mgr.rollback(self.pid, c1)
        self.mgr.rollback(self.pid, res["safety_checkpoint"][0])
        self.assertEqual(self.mgr.read_file(self.pid, "a.txt"), b"v2")

    def test_rollback_recovers_missing_file(self):
        self.mgr.write_file(self.pid, "a.txt", "v1")
        cid = self.mgr.create_checkpoint(self.pid)
        (self.pdir() / "a.txt").unlink()
        self.mgr.rollback(self.pid, cid)
        self.assertEqual(self.mgr.read_file(self.pid, "a.txt"), b"v1")

    def test_rollback_blocked_by_untracked_collision(self):
        self.mgr.write_file(self.pid, "a.txt", "v1")
        cid = self.mgr.create_checkpoint(self.pid)
        self.mgr.delete_file(self.pid, "a.txt", approval=ok("delete_file"))
        (self.pdir() / "a.txt").write_text("user replaced")
        with self.assertRaises(CollisionError):
            self.mgr.rollback(self.pid, cid)
        self.assertEqual((self.pdir() / "a.txt").read_text(), "user replaced")

    def test_corrupted_checkpoint_rejected_without_changes(self):
        self.mgr.write_file(self.pid, "a.txt", "v1")
        cid = self.mgr.create_checkpoint(self.pid)
        self.mgr.write_file(self.pid, "a.txt", "v2", overwrite=True, approval=ok("overwrite_file"))
        (self.pdir() / ".creator" / "checkpoints" / cid / "files" / "a.txt").write_text("corrupt")
        with self.assertRaises(CreatorWorkspaceError):
            self.mgr.rollback(self.pid, cid)
        self.assertEqual(self.mgr.read_file(self.pid, "a.txt"), b"v2")

    def test_invalid_checkpoint_ids(self):
        for bad in ("../x", "ckpt_9999", "", "ckpt_1"):
            with self.assertRaises(CreatorWorkspaceError):
                self.mgr.rollback(self.pid, bad)


class TestIsolationAndAuthorization(Base):
    def test_projects_isolated(self):
        p2 = self.mgr.create_project("other")
        self.mgr.write_file(self.pid, "a.txt", "one")
        self.assertEqual(self.mgr.manifest(p2), {})
        with self.assertRaises(CreatorWorkspaceError):
            self.mgr.read_file(p2, "a.txt")
        with self.assertRaises(PathViolation):
            self.mgr.read_file(self.pid, f"../{p2}/.creator/project.json")
        c = self.mgr.create_checkpoint(self.pid)
        self.mgr.write_file(p2, "x.txt", "x")
        self.assertEqual(self.mgr.list_checkpoints(p2), [])
        with self.assertRaises(CreatorWorkspaceError):
            self.mgr.rollback(p2, c)

    def test_delete_requires_approval(self):
        self.mgr.write_file(self.pid, "a.txt", "x")
        with self.assertRaises(ApprovalRequired):
            self.mgr.delete_file(self.pid, "a.txt")
        with self.assertRaises(ApprovalRequired):
            self.mgr.delete_file(self.pid, "a.txt", approval=ok("overwrite_file"))
        self.assertTrue((self.pdir() / "a.txt").exists())
        self.mgr.delete_file(self.pid, "a.txt", approval=ok("delete_file"))
        self.assertFalse((self.pdir() / "a.txt").exists())
        self.assertEqual(len(list((self.pdir() / ".creator" / "backups").rglob("a.txt"))), 1)

    def test_cannot_delete_untracked_user_file(self):
        (self.pdir() / "mine.txt").write_text("u")
        with self.assertRaises(CreatorWorkspaceError):
            self.mgr.delete_file(self.pid, "mine.txt", approval=ok("delete_file"))
        self.assertTrue((self.pdir() / "mine.txt").exists())

    def test_unapproved_denials_are_audited(self):
        with self.assertRaises(ApprovalRequired):
            self.mgr.delete_file(self.pid, "a.txt")
        self.assertTrue(any(r["action"] == "delete_file" and r["outcome"] == "denied"
                            for r in self.audit.records(self.pid)))
        self.assertTrue(self.audit.verify_chain())

    def test_module_never_executes_code(self):
        src = Path(wm.__file__).read_text()
        for banned in ("subprocess", "os.system", "exec(", "eval(", "shell=True", "popen", "import socket"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
