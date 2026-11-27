"""Creator Engine C1 tests (unittest-style; also collected by pytest)."""

import tempfile
import unittest
from pathlib import Path

from jarvis.core.approval import ApprovalDecision
from jarvis.creator import AuditLogger, CreatorOrchestrator, ProjectType, SecurityGate, TaskContract, TaskStatus
from jarvis.creator.agents import AgentDispatcher, FORBIDDEN_FOR_ALL
from jarvis.creator.contracts import CreatorPhase
from jarvis.creator.stacks import IMPLEMENTED_GENERATORS, detect_project_type, select_stack

SITE = "Build a website for my bakery with a menu page, a contact form and an about section. It must work offline."


class TestPlanner(unittest.TestCase):
    def test_website_plan(self):
        plan, err = CreatorOrchestrator().plan(SITE)
        self.assertIsNone(err)
        self.assertEqual(plan.project_type, ProjectType.STATIC_WEBSITE)
        agents = [t["agent"] for t in plan.agent_tasks]
        self.assertIn("uiux_design", agents)
        self.assertIn("frontend", agents)
        self.assertNotIn("backend", agents)
        self.assertTrue(plan.mock)
        self.assertTrue(any("BLOCKED" in w for w in plan.warnings))
        self.assertTrue(any("inferred" in a for a in plan.requirements["spec"]["assumptions"]))
        self.assertEqual(plan.phases[0], "plan")
        self.assertEqual(plan.phases[-1], "deliver")

    def test_vague_request_rejected(self):
        plan, err = CreatorOrchestrator().plan("make it good")
        self.assertIsNone(plan)
        self.assertTrue(err)

    def test_empty_request(self):
        plan, err = CreatorOrchestrator().plan("")
        self.assertIsNone(plan)
        self.assertTrue(err)

    def test_no_generator_claimed(self):
        self.assertEqual(IMPLEMENTED_GENERATORS, frozenset())
        for ptype in ProjectType:
            self.assertFalse(select_stack(ptype).generator_available)

    def test_type_detection(self):
        self.assertEqual(detect_project_type("a FastAPI service"), ProjectType.FASTAPI_BACKEND)
        self.assertEqual(detect_project_type("a pygame platformer game"), ProjectType.GAME_SCAFFOLD)
        self.assertEqual(detect_project_type("zzz"), ProjectType.UNKNOWN)

    def test_plan_serialises(self):
        plan, _ = CreatorOrchestrator().plan(SITE)
        import json
        json.dumps(plan.to_dict())


class TestSecurityGate(unittest.TestCase):
    def setUp(self):
        self.audit = AuditLogger()
        self.gate = SecurityGate(self.audit)

    def test_execution_blocked_even_with_approval(self):
        for action in ("execute_code", "run_generated_script", "run_downloaded_code", "run_plugin"):
            approval = ApprovalDecision(action=action, approved=True, reviewer="user")
            d = self.gate.check("p1", "agent", action, approval)
            self.assertFalse(d.allowed, action)

    def test_automatic_actions(self):
        self.assertTrue(self.gate.check("p1", "a", "static_analysis").allowed)
        self.assertTrue(self.gate.check("p1", "a", "create_workspace").allowed)

    def test_approval_required(self):
        d = self.gate.check("p1", "a", "install_dependencies")
        self.assertFalse(d.allowed)
        self.assertTrue(d.needs_approval)
        ok = ApprovalDecision(action="install_dependencies", approved=True, reviewer="user")
        self.assertTrue(self.gate.check("p1", "a", "install_dependencies", ok).allowed)
        wrong = ApprovalDecision(action="publish", approved=True, reviewer="user")
        self.assertFalse(self.gate.check("p1", "a", "install_dependencies", wrong).allowed)

    def test_unknown_action_denied(self):
        self.assertFalse(self.gate.check("p1", "a", "format_disk").allowed)

    def test_audit_chain(self):
        self.gate.check("p1", "a", "plan")
        self.gate.check("p1", "a", "execute_code")
        self.assertTrue(self.audit.verify_chain())
        self.audit._records[0]["outcome"] = "tampered"
        self.assertFalse(self.audit.verify_chain())

    def test_audit_redacts_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            log = AuditLogger(Path(d) / "audit.jsonl")
            log.record("p", "a", "x", "ok", "key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
            text = (Path(d) / "audit.jsonl").read_text()
            self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", text)


class TestAgents(unittest.TestCase):
    def test_ten_agents_no_forbidden_permissions(self):
        disp = AgentDispatcher()
        self.assertEqual(len(disp.specs), 10)
        for spec in disp.specs.values():
            self.assertFalse(spec.permissions & FORBIDDEN_FOR_ALL, spec.name)

    def _contract(self, **kw):
        base = dict(task_id="t1", project_id="p1", agent="architect", phase=CreatorPhase.PLAN,
                    inputs={"requirements": {}}, timeout_seconds=10)
        base.update(kw)
        return TaskContract(**base)

    def test_unimplemented_agent_blocked_not_faked(self):
        r = AgentDispatcher().dispatch(self._contract())
        self.assertEqual(r.status, TaskStatus.BLOCKED)

    def test_handler_success_and_output_contract(self):
        d = AgentDispatcher()
        d.register("architect", lambda c: {"design": {"ok": 1}})
        self.assertEqual(d.dispatch(self._contract()).status, TaskStatus.DONE)
        d.register("architect", lambda c: {})
        self.assertEqual(d.dispatch(self._contract()).status, TaskStatus.FAILED)

    def test_handler_exception_contained(self):
        d = AgentDispatcher()
        def boom(c):
            raise RuntimeError("x")
        d.register("architect", boom)
        r = d.dispatch(self._contract())
        self.assertEqual(r.status, TaskStatus.FAILED)
        self.assertIn("RuntimeError", r.error)

    def test_bad_contracts(self):
        d = AgentDispatcher()
        self.assertEqual(d.dispatch(self._contract(inputs={})).status, TaskStatus.FAILED)
        self.assertEqual(d.dispatch(self._contract(timeout_seconds=999)).status, TaskStatus.FAILED)
        self.assertEqual(d.dispatch(self._contract(agent="nope")).status, TaskStatus.FAILED)
        self.assertEqual(d.dispatch(self._contract(project_id="")).status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
