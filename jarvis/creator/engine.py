"""CreatorEngine (C10): the end-to-end pipeline.

request -> analyse/plan -> select generator -> workspace -> generate -> (smoke tests) -> static tests ->
debug loop -> re-test -> static preview -> package -> memory/audit.

Every stage is dispatched through the typed agent contracts of C1, gated by SecurityGate, and recorded as
evidence. Nothing generated is executed; success statements never exceed what was actually verified."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from jarvis.creator import spec_builder
from jarvis.creator.agents import AgentDispatcher
from jarvis.creator.ai_assist import AIAssist
from jarvis.creator.audit import AuditLogger
from jarvis.creator.codegen_manager import CodeGenerationManager, GenerationError
from jarvis.creator.contracts import CreatorPhase, ProjectType, TaskContract, TaskStatus
from jarvis.creator.debug_manager import DebugManager
from jarvis.creator.delivery_manager import DeliveryManager, DeliveryRefused
from jarvis.creator.orchestrator import CreatorOrchestrator
from jarvis.creator.preview_manager import PreviewManager
from jarvis.creator.project_memory import CreatorProjectMemory
from jarvis.creator.security_gate import SecurityGate
from jarvis.creator.spec_utils import SpecError, slugify
from jarvis.creator.testing_engine import TestGenerator, TestManager
from jarvis.creator.workspace_manager import CreatorWorkspaceError, CreatorWorkspaceManager

STAGES = ("plan", "workspace", "generate", "tests_generate", "static_test", "debug", "retest", "preview", "package")
STAGE_AGENT = {"plan": "architect", "workspace": "architect", "generate": "codegen", "tests_generate": "testing",
               "static_test": "testing", "debug": "debugging", "retest": "testing", "preview": "delivery", "package": "delivery"}
MAX_REQUEST = 2000
EventCb = Callable[[dict[str, Any]], None]


@dataclass
class CreationResult:
    status: str  # delivered | static_verified | failed_static | needs_clarification | unsupported | failed | refused
    project_id: Optional[str] = None
    project_type: Optional[str] = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    test_report: dict[str, Any] = field(default_factory=dict)
    preview: dict[str, Any] = field(default_factory=dict)
    delivery: dict[str, Any] = field(default_factory=dict)
    ai_assist: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    message: str = ""
    runtime_verified: bool = False
    heuristic_spec: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class CreatorEngine:
    def __init__(self, root: Path, *, router: Any = None, approved_live_providers=(), audit_path: Optional[Path] = None,
                 on_event: Optional[EventCb] = None) -> None:
        self.audit = AuditLogger(audit_path)
        self.gate = SecurityGate(self.audit)
        self.ws = CreatorWorkspaceManager(Path(root), self.gate, self.audit)
        self.gen = CodeGenerationManager(self.ws, self.gate, self.audit)
        self.tests = TestManager(self.ws, self.gate, self.audit)
        self.tgen = TestGenerator(self.ws, self.gate)
        self.debug = DebugManager(self.ws, self.audit)
        self.preview = PreviewManager(self.ws, self.gate, self.audit)
        self.delivery = DeliveryManager(self.ws, self.gate, self.audit)
        self.orch = CreatorOrchestrator(self.audit)
        self.dispatcher: AgentDispatcher = self.orch.dispatcher
        self.assist = AIAssist(router, approved_live_providers)
        self.on_event = on_event
        self._lock = threading.Lock()
        self._events: dict[str, list[dict[str, Any]]] = {}

    # ---------- events / agents ----------
    def events(self, pid: str) -> list[dict[str, Any]]:
        return list(self._events.get(pid, []))

    def _emit(self, pid: Optional[str], stage: str, status: str, detail: str = "", **evidence: Any) -> dict[str, Any]:
        ev = {"stage": stage, "agent": STAGE_AGENT.get(stage, "orchestrator"), "status": status, "detail": detail[:300],
              "evidence": evidence, "step": STAGES.index(stage) + 1 if stage in STAGES else 0, "of": len(STAGES)}
        self._events.setdefault(pid or "pending", []).append(ev)
        if self.on_event:
            try:
                self.on_event(dict(ev, project_id=pid))
            except Exception:
                pass  # UI callbacks must never break the pipeline
        return ev

    def _agent(self, pid: str, agent: str, phase: CreatorPhase, inputs: dict[str, Any], fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        spec = self.dispatcher.specs[agent]
        self.dispatcher.register(agent, lambda _c: fn())
        contract = TaskContract(f"{pid}:{agent}:{phase.value}", pid, agent, phase, inputs, timeout_seconds=spec.timeout_seconds)
        res = self.dispatcher.dispatch(contract)
        self.audit.record(pid, agent, f"task_{phase.value}", res.status.value, res.error or "")
        if res.status is not TaskStatus.DONE:
            raise CreatorWorkspaceError(res.error or f"agent {agent} {res.status.value}")
        return res.outputs

    # ---------- main pipeline ----------
    def create(self, request: str, *, project_name: Optional[str] = None, spec: Optional[dict] = None,
               composer_id: Optional[str] = None, auto_package: bool = True, ai_provider: Optional[str] = None) -> CreationResult:
        if not isinstance(request, str) or not request.strip() or len(request) > MAX_REQUEST:
            return CreationResult("needs_clarification", error="request must be 1..2000 characters", message="Please describe the project.")
        request = " ".join(request.split())
        res = CreationResult("failed")
        plan, err = self.orch.plan(request)
        if plan is None:
            self._emit(None, "plan", "needs_clarification", err or "")
            res.status, res.error = "needs_clarification", err
            res.message = "I need a few more details before building: " + (err or "")
            res.stages = self.events("pending")
            self._events.pop("pending", None)
            return res
        ptype = plan.project_type
        res.project_type = ptype.value
        res.plan = {"project_type": ptype.value, "stack": plan.stack.to_dict(), "phases": plan.phases,
                    "agent_tasks": plan.agent_tasks, "warnings": plan.warnings}
        choice = ({"kind": "composer", "id": composer_id, "spec": spec, "assumptions": ["explicit spec supplied"]}
                  if spec is not None and composer_id else spec_builder.build(request, ptype))
        res.heuristic_spec = not (spec is not None and composer_id)
        res.assumptions = list(choice["assumptions"])
        if choice["kind"] == "unsupported":
            res.status, res.message = "unsupported", "; ".join(choice["assumptions"][1:]) or "unsupported project type"
            self._emit(None, "plan", "unsupported", res.message)
            self.audit.record("pending", "engine", "create", "unsupported", ptype.value)
            res.stages = self.events("pending")
            self._events.pop("pending", None)
            return res

        # ---- workspace
        base = project_name or (choice["spec"].get("site_name") or choice["spec"].get("project_name") or choice["spec"].get("app_name")
                                or choice["spec"].get("game_name") or "project")
        try:
            pid = self.ws.create_project(slugify(str(base))[:40] or "project", ptype.value)
        except CreatorWorkspaceError as exc:
            res.error = str(exc)
            res.message = f"Could not create a workspace: {exc}"
            return res
        res.project_id = pid
        mem = CreatorProjectMemory(self.ws, pid)
        mem.add("requirements", {"request": request, "assumptions": res.assumptions})
        mem.add("stack", plan.stack.to_dict())
        mem.add("phase", {"phase": "plan"})
        self._emit(pid, "plan", "done", f"{ptype.value}", warnings=plan.warnings)
        self._agent(pid, "architect", CreatorPhase.PLAN, {"requirements": plan.requirements}, lambda: {"design": plan.design})
        self._emit(pid, "workspace", "done", f"workspace {pid}")
        res.ai_assist = self.assist.advise(request, f"{ptype.value} via {choice['id']}", ai_provider)
        mem.add("decision", {"generator": choice["id"], "kind": choice["kind"], "ai_assist_mode": res.ai_assist.get("mode")})

        # ---- generate
        try:
            def do_generate():
                if choice["kind"] == "composer":
                    rec = self.gen.compose(pid, choice["id"], choice["spec"])
                else:
                    rec = self.gen.generate(pid, choice["id"], choice["spec"])
                return {"files": rec}
            rec = self._agent(pid, "codegen", CreatorPhase.GENERATE, {"plan": res.plan}, do_generate)["files"]
        except (GenerationError, SpecError, CreatorWorkspaceError) as exc:
            self._emit(pid, "generate", "failed", str(exc))
            mem.add("known_error", {"stage": "generate", "error": str(exc)[:500]})
            res.status, res.error, res.message = "failed", str(exc), f"Generation failed: {exc}"
            res.stages = self.events(pid)
            return res
        self._emit(pid, "generate", "done", f"{len(rec['written'])} files", generation_id=rec["generation_id"], digest=rec["content_digest"][:16])
        mem.add("phase", {"phase": "generate", "generation_id": rec["generation_id"]})

        # ---- tests
        added = self.tgen.generate(pid)
        self._emit(pid, "tests_generate", "done" if added else "skipped", ", ".join(added) or "project already has tests or no python sources")
        report = self._agent(pid, "testing", CreatorPhase.TEST, {"files": rec["written"]}, lambda: {"tests": self.tests.run(pid)})["tests"]
        self._emit(pid, "static_test", "passed" if report["completion"]["complete"] else "failed", report["completion"]["status"],
                   errors=sum(1 for f in report["findings"] if f["severity"] == "error"))
        if not report["completion"]["complete"]:
            failures = [f for f in report["findings"] if f["severity"] == "error"]
            dbg = self._agent(pid, "debugging", CreatorPhase.DIAGNOSE, {"failures": failures}, lambda: {"proposals": self.debug.run(pid)})["proposals"]
            self._emit(pid, "debug", "resolved" if dbg["resolved"] else "unresolved", f"{dbg['errors_before']} -> {dbg['errors_after']} errors, {len(dbg['rounds'])} rounds")
            report = self.tests.run(pid)
            self._emit(pid, "retest", "passed" if report["completion"]["complete"] else "failed", report["completion"]["status"])
            if not report["completion"]["complete"]:
                mem.add("known_error", {"stage": "static", "remaining": [f["message"] for f in report["findings"] if f["severity"] == "error"][:10]})
        mem.add("test_result", {"status": report["completion"]["status"], "runtime": "blocked"})

        # ---- preview
        pv = self.preview.build_static_preview(pid)
        res.preview = {k: v for k, v in pv.items() if k in ("supported", "mode", "built", "reason", "pages", "server_started", "executed")}
        self._emit(pid, "preview", "built" if pv.get("built") else "blocked" if not pv.get("supported") else "refused", pv.get("mode", ""))

        # ---- package
        res.test_report = {"completion": report["completion"], "categories": {k: v["status"] for k, v in report["categories"].items()},
                           "findings": report["findings"][:50]}
        res.files = self.ws.inventory(pid)
        if report["completion"]["complete"] and auto_package:
            try:
                rec_d = self._agent(pid, "delivery", CreatorPhase.DELIVER, {"report": report["completion"]}, lambda: {"summary": self.delivery.package(pid)})["summary"]
                res.delivery = rec_d
                res.status = "delivered"
                self._emit(pid, "package", "done", f"v{rec_d['version']}", zip_sha256=rec_d["zip_sha256"][:16])
                mem.add("delivery_status", {"version": rec_d["version"], "sha256": rec_d["zip_sha256"], "runtime_verified": False})
                res.message = (f"Project '{base}' created and statically verified ({len(res.files)} files). "
                               "The code was NOT run: execution is blocked until OS-level isolation is verified.")
            except DeliveryRefused as exc:
                res.status, res.error, res.message = "refused", str(exc), f"Delivery refused: {exc}"
                self._emit(pid, "package", "refused", str(exc))
        elif report["completion"]["complete"]:
            res.status, res.message = "static_verified", "Generated and statically verified; packaging skipped."
        else:
            res.status = "failed_static"
            res.message = "Files were generated but static checks still fail; not delivered. See the error report."
            self._emit(pid, "package", "refused", "static checks failed")
        res.stages = self.events(pid)
        self.audit.record(pid, "engine", "create", res.status, ptype.value)
        return res

    # ---------- queries ----------
    def projects(self) -> list[dict[str, Any]]:
        out = []
        for pid in self.ws.list_projects():
            m = self.ws.metadata(pid)
            out.append({"project_id": pid, "name": m["name"], "project_type": m["project_type"], "created_at": m["created_at"],
                        "deliveries": len(self.ws.list_control_records(pid, "delivery"))})
        return out

    def file_tree(self, pid: str) -> dict[str, Any]:
        tree: dict[str, Any] = {}
        for item in self.ws.inventory(pid):
            node = tree
            parts = item["path"].split("/")
            for p in parts[:-1]:
                node = node.setdefault(p + "/", {})
            node[parts[-1]] = {"size": item["size"], "sha256": item["sha256"][:12]}
        return tree
