"""Specialized deterministic agents for Phase 4 orchestration.

All agents default to DETERMINISTIC mode so mandatory tests run offline.
They produce verifiable structured outputs without requiring live LLM calls.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from jarvis.core.models import AgentResult, TaskRecord
from jarvis.core.agents.base import BaseAgent


class PlannerAgent(BaseAgent):
    name = "planner"
    role = "Planner"
    capabilities = ["plan", "decompose"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        objective = task.inputs.get("objective") or task.objective or task.description
        # Deterministic decomposition: produce ordered subtask templates
        steps = [
            {"name": "research", "agent": "researcher", "desc": f"Research context for: {objective}"},
            {"name": "design", "agent": "architect", "desc": f"Propose structure for: {objective}"},
            {"name": "implement", "agent": "coder", "desc": f"Implement scoped work for: {objective}"},
            {"name": "test", "agent": "tester", "desc": f"Test results for: {objective}"},
            {"name": "review", "agent": "reviewer", "desc": f"Review deliverable for: {objective}"},
            {"name": "document", "agent": "documentation", "desc": f"Document outcome for: {objective}"},
        ]
        # Allow simpler plans for simple objectives
        if task.inputs.get("simple"):
            steps = [
                {"name": "implement", "agent": "coder", "desc": f"Do: {objective}"},
                {"name": "test", "agent": "tester", "desc": f"Verify: {objective}"},
            ]
        return AgentResult(
            success=True,
            outputs={"plan": steps, "objective": objective, "step_count": len(steps)},
            mode=self.mode,
            notes="Deterministic plan generated",
        )


class ResearcherAgent(BaseAgent):
    name = "researcher"
    role = "Researcher"
    capabilities = ["research", "gather"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        query = task.inputs.get("query") or task.description
        # Use skill registry / memory from context if provided
        skills = []
        memories = []
        if context.get("skill_registry") is not None:
            try:
                skills = [
                    {"name": s.name, "status": s.status}
                    for s in context["skill_registry"].search(query=str(query)[:40], limit=5)
                ]
            except Exception as exc:
                skills = [{"error": str(exc)}]
        if context.get("memory_store") is not None:
            try:
                hits = context["memory_store"].search(str(query)[:40], limit=5)
                memories = [{"content": h.content[:80], "category": h.category} for h in hits]
            except Exception as exc:
                memories = [{"error": str(exc)}]
        evidence = {
            "query": query,
            "skills_found": skills,
            "memories_found": memories,
            "notes": "Local research only (no external network in DETERMINISTIC mode)",
        }
        return AgentResult(success=True, outputs={"evidence": evidence}, mode=self.mode)


class PromptEngineerAgent(BaseAgent):
    name = "prompt_engineer"
    role = "Prompt Engineer"
    capabilities = ["prompt", "acceptance_criteria"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        objective = task.inputs.get("objective") or task.description
        prompt = {
            "instruction": f"Complete the following objective carefully: {objective}",
            "acceptance": [
                "Produce structured output",
                "Do not invent external side effects",
                "Report failures honestly",
            ],
        }
        return AgentResult(success=True, outputs={"prompt": prompt}, mode=self.mode)


class ArchitectAgent(BaseAgent):
    name = "architect"
    role = "Architect"
    capabilities = ["architecture", "design"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        objective = task.inputs.get("objective") or task.description
        design = {
            "modules": ["input", "core_logic", "output"],
            "boundaries": "Keep side effects scoped to workspace",
            "objective": objective,
        }
        return AgentResult(success=True, outputs={"architecture": design}, mode=self.mode)


class CoderAgent(BaseAgent):
    name = "coder"
    role = "Coder"
    capabilities = ["code", "implement", "write_file"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        workspace = Path(context.get("workspace") or task.inputs.get("workspace") or ".")
        workspace = Path(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        # Path safety: reject traversal outside workspace
        rel = task.inputs.get("filename", "artifact.txt")
        if ".." in str(rel) or str(rel).startswith("/") or "\\" in str(rel):
            return AgentResult(success=False, error="Path traversal rejected", mode=self.mode)
        target = workspace / rel
        # Ensure resolved path stays under workspace
        try:
            target.resolve().relative_to(workspace.resolve())
        except ValueError:
            return AgentResult(success=False, error="Path escapes workspace", mode=self.mode)

        content = task.inputs.get("content")
        if content is None:
            objective = task.inputs.get("objective") or task.description
            content = f"# Generated artifact for: {objective}\n"
        # Force fail if requested (for retry tests)
        if task.inputs.get("force_fail"):
            if task.attempt_count < int(task.inputs.get("fail_until_attempt", 99)):
                return AgentResult(
                    success=False,
                    error="Forced coder failure for retry testing",
                    mode=self.mode,
                )
        target.write_text(str(content), encoding="utf-8")
        digest = hashlib.sha256(str(content).encode("utf-8")).hexdigest()[:16]
        return AgentResult(
            success=True,
            outputs={"path": str(target), "bytes": len(str(content)), "sha16": digest},
            mode=self.mode,
        )


class TesterAgent(BaseAgent):
    name = "tester"
    role = "Tester"
    capabilities = ["test", "verify"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        path = task.inputs.get("path") or context.get("last_artifact_path")
        if not path:
            return AgentResult(success=False, error="No path to test", mode=self.mode)
        p = Path(path)
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        ok = exists and size > 0
        return AgentResult(
            success=ok,
            outputs={"path": str(p), "exists": exists, "size": size, "passed": ok},
            error=None if ok else "Artifact missing or empty",
            mode=self.mode,
        )


class DebuggerAgent(BaseAgent):
    name = "debugger"
    role = "Debugger"
    capabilities = ["debug", "fix"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        error = task.inputs.get("error") or context.get("last_error") or "unknown"
        suggestion = f"Inspect error and retry with corrected inputs: {error}"
        return AgentResult(
            success=True,
            outputs={"analysis": suggestion, "error": error},
            mode=self.mode,
        )


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    role = "Reviewer"
    capabilities = ["review", "qa"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        checks = {
            "has_artifact": bool(context.get("last_artifact_path")),
            "tests_passed": bool(context.get("tests_passed", True)),
            "no_secrets": True,
        }
        # Scan artifact for secret-like content if present
        path = context.get("last_artifact_path")
        if path and Path(path).exists():
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
            if re.search(r"(?i)(api[_\s-]?key|password)\s*[:=]", text) or "sk-" in text:
                checks["no_secrets"] = False
        ok = all(checks.values())
        return AgentResult(
            success=ok,
            outputs={"checks": checks, "approved": ok},
            error=None if ok else "Review failed",
            mode=self.mode,
        )


class DocumentationAgent(BaseAgent):
    name = "documentation"
    role = "Documentation"
    capabilities = ["docs", "document"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        workspace = Path(context.get("workspace") or ".")
        workspace.mkdir(parents=True, exist_ok=True)
        doc_path = workspace / "ORCHESTRATION_NOTES.md"
        objective = task.inputs.get("objective") or task.description
        body = f"# Orchestration Notes\n\nObjective: {objective}\n\nStatus: documented\n"
        doc_path.write_text(body, encoding="utf-8")
        return AgentResult(
            success=True,
            outputs={"doc_path": str(doc_path)},
            mode=self.mode,
        )


class ProjectManagerAgent(BaseAgent):
    name = "project_manager"
    role = "Project Manager"
    capabilities = ["track", "status", "pm"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        tasks = context.get("tasks") or []
        summary = {
            "total": len(tasks),
            "completed": sum(1 for t in tasks if getattr(t, "status", "") == "COMPLETED"),
            "failed": sum(1 for t in tasks if getattr(t, "status", "") == "FAILED"),
        }
        return AgentResult(success=True, outputs={"summary": summary}, mode=self.mode)


class ResourceFinderAgent(BaseAgent):
    name = "resource_finder"
    role = "Resource Finder"
    capabilities = ["resources", "dependencies"]
    mode = "DETERMINISTIC"

    def execute(self, task: TaskRecord, context: dict[str, Any]) -> AgentResult:
        need = task.inputs.get("need") or task.description
        intent = str(task.inputs.get("intent") or "find").lower().strip()
        acquisition = context.get("resource_acquisition")

        # Prefer acquisition service when present (Phase E)
        if acquisition is not None:
            from jarvis.resources.acquisition import AcquisitionRequest

            req = AcquisitionRequest(
                need=str(need),
                intent=intent,
                project=task.inputs.get("project"),
                preferred_url=task.inputs.get("url") or task.inputs.get("preferred_url"),
                resource_id=task.inputs.get("resource_id"),
                category=str(task.inputs.get("category") or ""),
                limit=int(task.inputs.get("limit") or 5),
                filename=task.inputs.get("filename"),
                expected_sha256=task.inputs.get("expected_sha256"),
                overwrite=bool(task.inputs.get("overwrite") or False),
            )
            report = acquisition.run(req)
            return AgentResult(
                success=report.success,
                outputs=report.to_dict(),
                error=report.error,
                mode=self.mode,
            )

        finder = context.get("resource_finder")
        if finder is not None:
            result = finder.find(str(need), limit=5)
            return AgentResult(
                success=result.error is None,
                outputs={
                    "query": result.query,
                    "candidates": [
                        {
                            "title": c.title,
                            "url": c.url,
                            "score": c.score,
                            "reasons": c.reasons,
                            "source": c.source,
                            "kind": c.kind,
                        }
                        for c in result.candidates
                    ],
                    "mode": result.mode,
                    "consulted": result.consulted,
                    "notes": result.notes,
                    "intent": "find",
                },
                error=result.error,
                mode=self.mode,
            )
        # Offline local suggestions only — never invent URLs
        suggestions = [
            {"name": "stdlib", "reason": f"Prefer standard library for: {need}"},
            {"name": "existing_skill", "reason": "Check SkillRegistry before new deps"},
        ]
        return AgentResult(success=True, outputs={"suggestions": suggestions, "mode": "OFFLINE"}, mode=self.mode)


def build_default_agents() -> list[BaseAgent]:
    return [
        PlannerAgent(),
        ResearcherAgent(),
        PromptEngineerAgent(),
        ArchitectAgent(),
        CoderAgent(),
        TesterAgent(),
        DebuggerAgent(),
        ReviewerAgent(),
        DocumentationAgent(),
        ProjectManagerAgent(),
        ResourceFinderAgent(),
    ]
