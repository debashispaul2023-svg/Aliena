"""CreatorOrchestrator (C1): requirements -> architecture -> plan. No file generation yet."""

from __future__ import annotations

from typing import Optional

from jarvis.creator.agents import AgentDispatcher
from jarvis.creator.audit import AuditLogger
from jarvis.creator.contracts import (CreatorPhase, CreatorPlan, ProjectType, TaskContract)
from jarvis.creator.requirement_analyzer import RequirementAnalyzer
from jarvis.creator.security_gate import SecurityGate
from jarvis.dev.stages.pipeline import run_pipeline

PHASES = [p.value for p in CreatorPhase]
_AGENT_FLOW = [
    ("architect", CreatorPhase.PLAN), ("uiux_design", CreatorPhase.PLAN),
    ("codegen", CreatorPhase.GENERATE), ("frontend", CreatorPhase.GENERATE),
    ("backend", CreatorPhase.GENERATE), ("database", CreatorPhase.GENERATE),
    ("testing", CreatorPhase.TEST), ("debugging", CreatorPhase.DIAGNOSE),
    ("documentation", CreatorPhase.GENERATE), ("delivery", CreatorPhase.DELIVER),
]
_RELEVANT = {
    ProjectType.STATIC_WEBSITE: {"frontend", "uiux_design"},
    ProjectType.REACT_APP: {"frontend", "uiux_design"},
    ProjectType.NEXTJS_APP: {"frontend", "backend", "uiux_design"},
    ProjectType.FASTAPI_BACKEND: {"backend", "database"},
    ProjectType.DATABASE_PROJECT: {"database", "backend"},
}
_OPTIONAL = {"frontend", "backend", "database", "uiux_design"}


class CreatorOrchestrator:
    def __init__(self, audit: Optional[AuditLogger] = None) -> None:
        self.audit = audit or AuditLogger()
        self.gate = SecurityGate(self.audit)
        self.dispatcher = AgentDispatcher()
        self.analyzer = RequirementAnalyzer()

    def plan(self, user_request: str, *, project_id: Optional[str] = None) -> tuple[Optional[CreatorPlan], Optional[str]]:
        """Returns (plan, error). error set with plan=None when requirements are insufficient."""
        pid = project_id or "pending"
        if not self.gate.check(pid, "orchestrator", "plan").allowed:
            return None, "planning denied"
        analysis = self.analyzer.analyze(user_request)
        res = run_pipeline(user_request, project_id=project_id, context=analysis.context)
        if not res.success:
            self.audit.record(pid, "orchestrator", "plan", "incomplete", res.error or "")
            questions = res.requirements.spec.clarifying_questions if res.requirements and res.requirements.spec else []
            return None, (res.error or "planning failed") + (f"; questions: {questions}" if questions else "")
        spec = res.requirements.spec
        pid = spec.project_id
        ptype, stack = analysis.project_type, analysis.stack
        spec.assumptions.append(analysis.assumption)
        warnings = []
        if ptype is ProjectType.UNKNOWN:
            warnings.append("project type not recognised; choose one before generation")
        if not stack.generator_available:
            warnings.append(f"no generator for {ptype.value} yet; generation unavailable in this phase")
        warnings.append("generated-code execution is BLOCKED; static analysis only")
        relevant = _RELEVANT.get(ptype, set())
        tasks = [
            {"agent": a, "phase": ph.value, "task_id": f"{pid}:{a}"}
            for a, ph in _AGENT_FLOW if a not in _OPTIONAL or a in relevant
        ]
        plan = CreatorPlan(
            project_id=pid, project_type=ptype, stack=stack, phases=list(PHASES),
            agent_tasks=tasks, requirements=res.requirements.to_dict(),
            design=res.architecture.to_dict(), implementation_plan=res.planning.to_dict(),
            approvals_required=["install_dependencies", "modify_existing_project", "publish", "deploy"],
            warnings=warnings,
        )
        self.audit.record(pid, "orchestrator", "plan", "ok", ptype.value)
        return plan, None
