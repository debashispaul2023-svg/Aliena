"""Multi-agent orchestrator: plan, schedule, execute, record."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from jarvis.core.models import (
    TaskRecord,
    AgentResult,
    OrchestrationResult,
    utc_now,
    STATUS_PLANNED,
    STATUS_READY,
    STATUS_RUNNING,
    STATUS_RETRYING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_REQUIRES_APPROVAL,
    STATUS_WAITING,
    TRANSITIONS,
    TERMINAL,
)
from jarvis.core.task_graph import TaskGraph, CycleError, UnknownDependencyError
from jarvis.core.agent_registry import AgentRegistry
from jarvis.core.agents import build_default_agents


class Orchestrator:
    """Coordinates specialized agents through a dependency-aware task graph.

    Execution is sequential and deterministic by default. Agents run real local
    logic (file writes, checks) — not print-only stubs.
    """

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        workspace: Optional[str | Path] = None,
        skill_registry: Any = None,
        memory_store: Any = None,
        experience_store: Any = None,
        learning_pipeline: Any = None,
        provider_router: Any = None,
        resource_finder: Any = None,
        resource_acquisition: Any = None,
        default_max_retries: int = 2,
    ) -> None:
        self.registry = registry or AgentRegistry()
        if registry is None:
            for agent in build_default_agents():
                self.registry.register(agent)
        self.workspace = Path(workspace or Path.cwd() / "orchestration_workspace")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.skill_registry = skill_registry
        self.memory_store = memory_store
        self.experience_store = experience_store
        self.learning_pipeline = learning_pipeline
        self.provider_router = provider_router
        self.resource_finder = resource_finder
        self.resource_acquisition = resource_acquisition
        self.default_max_retries = default_max_retries
        self._runs: dict[str, OrchestrationResult] = {}
        self._cancel_flags: set[str] = set()

    def transition(self, task: TaskRecord, new_status: str) -> None:
        allowed = TRANSITIONS.get(task.status, set())
        if new_status not in allowed:
            raise ValueError(f"Invalid transition {task.status} → {new_status}")
        task.status = new_status
        task.updated_at = utc_now()
        task.history.append({"status": new_status, "at": task.updated_at})

    def cancel_run(self, run_id: str) -> bool:
        self._cancel_flags.add(run_id)
        run = self._runs.get(run_id)
        if not run:
            return False
        for t in run.tasks:
            if t.status not in TERMINAL:
                try:
                    if t.status in (
                        STATUS_PLANNED,
                        STATUS_READY,
                        STATUS_WAITING,
                        STATUS_RUNNING,
                        STATUS_RETRYING,
                        STATUS_REQUIRES_APPROVAL,
                    ):
                        # force cancel from current state if allowed else mark cancelled directly
                        if STATUS_CANCELLED in TRANSITIONS.get(t.status, set()):
                            self.transition(t, STATUS_CANCELLED)
                        else:
                            t.status = STATUS_CANCELLED
                            t.updated_at = utc_now()
                        t.cancelled = True
                except ValueError:
                    t.status = STATUS_CANCELLED
                    t.cancelled = True
        run.status = STATUS_CANCELLED
        run.finished_at = utc_now()
        return True

    def get_run(self, run_id: str) -> Optional[OrchestrationResult]:
        return self._runs.get(run_id)

    def plan_simple(
        self,
        objective: str,
        *,
        simple: bool = False,
        force_fail: bool = False,
        fail_until_attempt: int = 99,
        requires_approval: bool = False,
        filename: str = "artifact.txt",
        content: Optional[str] = None,
    ) -> list[TaskRecord]:
        """Build a small dependency chain using planner output shape."""
        plan_task = TaskRecord.new(
            description=f"Plan: {objective}",
            agent_name="planner",
            inputs={"objective": objective, "simple": simple},
            objective=objective,
        )
        tasks = [plan_task]
        if simple:
            coder = TaskRecord.new(
                description=f"Implement: {objective}",
                agent_name="coder",
                dependencies=[plan_task.task_id],
                inputs={
                    "objective": objective,
                    "workspace": str(self.workspace),
                    "filename": filename,
                    "content": content if content is not None else f"result for {objective}\n",
                    "force_fail": force_fail,
                    "fail_until_attempt": fail_until_attempt,
                },
                requires_approval=requires_approval,
            )
            tester = TaskRecord.new(
                description=f"Test: {objective}",
                agent_name="tester",
                dependencies=[coder.task_id],
                inputs={},
            )
            tasks.extend([coder, tester])
        else:
            research = TaskRecord.new(
                description=f"Research: {objective}",
                agent_name="researcher",
                dependencies=[plan_task.task_id],
                inputs={"query": objective},
            )
            design = TaskRecord.new(
                description=f"Design: {objective}",
                agent_name="architect",
                dependencies=[research.task_id],
                inputs={"objective": objective},
            )
            coder = TaskRecord.new(
                description=f"Implement: {objective}",
                agent_name="coder",
                dependencies=[design.task_id],
                inputs={
                    "objective": objective,
                    "workspace": str(self.workspace),
                    "filename": filename,
                    "content": content if content is not None else f"result for {objective}\n",
                    "force_fail": force_fail,
                    "fail_until_attempt": fail_until_attempt,
                },
                requires_approval=requires_approval,
            )
            tester = TaskRecord.new(
                description=f"Test: {objective}",
                agent_name="tester",
                dependencies=[coder.task_id],
                inputs={},
            )
            reviewer = TaskRecord.new(
                description=f"Review: {objective}",
                agent_name="reviewer",
                dependencies=[tester.task_id],
                inputs={},
            )
            docs = TaskRecord.new(
                description=f"Document: {objective}",
                agent_name="documentation",
                dependencies=[reviewer.task_id],
                inputs={"objective": objective},
            )
            tasks.extend([research, design, coder, tester, reviewer, docs])
        return tasks

    def run(
        self,
        objective: str,
        tasks: Optional[list[TaskRecord]] = None,
        *,
        simple: bool = False,
        force_fail: bool = False,
        fail_until_attempt: int = 99,
        requires_approval: bool = False,
        record_experience: bool = True,
        content: Optional[str] = None,
        filename: str = "artifact.txt",
    ) -> OrchestrationResult:
        run_id = str(uuid.uuid4())
        created = utc_now()
        if tasks is None:
            tasks = self.plan_simple(
                objective,
                simple=simple,
                force_fail=force_fail,
                fail_until_attempt=fail_until_attempt,
                requires_approval=requires_approval,
                content=content,
                filename=filename,
            )

        graph = TaskGraph(tasks)
        try:
            graph.validate()
        except (CycleError, UnknownDependencyError) as exc:
            result = OrchestrationResult(
                run_id=run_id,
                objective=objective,
                status=STATUS_FAILED,
                tasks=tasks,
                error=str(exc),
                created_at=created,
                finished_at=utc_now(),
            )
            self._runs[run_id] = result
            return result

        context: dict[str, Any] = {
            "workspace": str(self.workspace),
            "skill_registry": self.skill_registry,
            "memory_store": self.memory_store,
            "provider_router": self.provider_router,
            "resource_finder": self.resource_finder,
            "resource_acquisition": getattr(self, "resource_acquisition", None),
            "tasks": tasks,
        }

        # Sequential execution in topological order
        try:
            order = graph.topological_order()
        except CycleError as exc:
            result = OrchestrationResult(
                run_id=run_id,
                objective=objective,
                status=STATUS_FAILED,
                tasks=tasks,
                error=str(exc),
                created_at=created,
                finished_at=utc_now(),
            )
            self._runs[run_id] = result
            return result

        for task in order:
            if run_id in self._cancel_flags:
                if task.status not in TERMINAL:
                    task.status = STATUS_CANCELLED
                    task.cancelled = True
                continue

            # Dependency failure propagation
            blocked = False
            for dep_id in task.dependencies:
                dep = graph.get(dep_id)
                if dep and dep.status in (STATUS_FAILED, STATUS_CANCELLED):
                    task.status = STATUS_FAILED
                    task.error = f"Dependency {dep_id} is {dep.status}"
                    task.finished_at = utc_now()
                    blocked = True
                    break
            if blocked:
                continue

            if task.requires_approval and not task.approved:
                task.status = STATUS_REQUIRES_APPROVAL
                task.updated_at = utc_now()
                result = OrchestrationResult(
                    run_id=run_id,
                    objective=objective,
                    status=STATUS_REQUIRES_APPROVAL,
                    tasks=tasks,
                    error="Approval required before continuing",
                    created_at=created,
                    finished_at=utc_now(),
                )
                self._runs[run_id] = result
                return result

            if not task.agent_name:
                task.status = STATUS_FAILED
                task.error = "No agent assigned"
                continue
            if not self.registry.has(task.agent_name):
                task.status = STATUS_FAILED
                task.error = f"Unknown agent: {task.agent_name}"
                continue

            agent = self.registry.get(task.agent_name)
            success = False
            while True:
                if run_id in self._cancel_flags:
                    task.status = STATUS_CANCELLED
                    task.cancelled = True
                    break
                task.attempt_count += 1
                task.status = STATUS_RUNNING if task.attempt_count == 1 else STATUS_RETRYING
                if task.attempt_count > 1:
                    task.status = STATUS_RETRYING
                task.started_at = task.started_at or utc_now()
                task.updated_at = utc_now()
                # inject prior outputs
                if context.get("last_artifact_path") and "path" not in task.inputs:
                    task.inputs["path"] = context["last_artifact_path"]
                try:
                    # mark running via transition rules when possible
                    ar: AgentResult = agent.execute(task, context)
                except Exception as exc:
                    ar = AgentResult(success=False, error=str(exc), mode=getattr(agent, "mode", "DETERMINISTIC"))

                if ar.success:
                    task.outputs = dict(ar.outputs)
                    task.status = STATUS_COMPLETED
                    task.finished_at = utc_now()
                    task.error = None
                    if "path" in ar.outputs:
                        context["last_artifact_path"] = ar.outputs["path"]
                    if ar.outputs.get("passed") is True:
                        context["tests_passed"] = True
                    if ar.outputs.get("passed") is False:
                        context["tests_passed"] = False
                    success = True
                    break
                else:
                    task.error = ar.error or "agent failed"
                    context["last_error"] = task.error
                    if task.attempt_count <= task.max_retries:
                        task.status = STATUS_RETRYING
                        continue
                    task.status = STATUS_FAILED
                    task.finished_at = utc_now()
                    break

            if not success and task.status not in TERMINAL:
                task.status = STATUS_FAILED
                task.finished_at = utc_now()

        # Aggregate
        if any(t.status == STATUS_CANCELLED for t in tasks) and run_id in self._cancel_flags:
            status = STATUS_CANCELLED
        elif any(t.status == STATUS_FAILED for t in tasks):
            status = STATUS_FAILED
        elif all(t.status == STATUS_COMPLETED for t in tasks):
            status = STATUS_COMPLETED
        elif any(t.status == STATUS_REQUIRES_APPROVAL for t in tasks):
            status = STATUS_REQUIRES_APPROVAL
        else:
            status = STATUS_FAILED

        final_output = {
            "artifacts": [t.outputs for t in tasks if t.outputs],
            "completed": sum(1 for t in tasks if t.status == STATUS_COMPLETED),
            "failed": sum(1 for t in tasks if t.status == STATUS_FAILED),
        }
        result = OrchestrationResult(
            run_id=run_id,
            objective=objective,
            status=status,
            tasks=tasks,
            final_output=final_output,
            error=None if status == STATUS_COMPLETED else "One or more tasks failed",
            created_at=created,
            finished_at=utc_now(),
            mode="DETERMINISTIC",
        )

        if record_experience and self.experience_store is not None:
            try:
                exp = self.experience_store.record(
                    task_id=run_id,
                    objective=objective,
                    task_plan=[t.description for t in tasks],
                    tools_used=["orchestrator"],
                    agents_used=sorted({t.agent_name for t in tasks if t.agent_name}),
                    skills_used=[],
                    errors=[t.error for t in tasks if t.error],
                    fixes=[],
                    resources=[],
                    test_results=[
                        {"name": t.description, "passed": t.status == STATUS_COMPLETED}
                        for t in tasks
                    ],
                    outcome="success" if status == STATUS_COMPLETED else "failure",
                    notes="orchestration run",
                    idempotent=True,
                )
                result.experience_id = exp.experience_id
            except Exception:
                pass

        self._runs[run_id] = result
        return result

    def approve_task(self, task_id: str) -> bool:
        for run in self._runs.values():
            for t in run.tasks:
                if t.task_id == task_id:
                    t.approved = True
                    if t.status == STATUS_REQUIRES_APPROVAL:
                        t.status = STATUS_READY
                    return True
        return False
