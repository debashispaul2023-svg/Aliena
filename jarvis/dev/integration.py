"""Phase 6G: offline development-engine integration.

Chains existing stages. Does not execute generated code.
Runtime testing remains BLOCKED until isolation is verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.dev.codegen import (
    GenerationResult,
    apply_generation,
    prepare_generation,
    propose_changes,
)
from jarvis.dev.models import SPEC_READY
from jarvis.dev.stages.architecture import ArchitectureResult, design_architecture
from jarvis.dev.stages.pipeline import PipelineResult, run_pipeline
from jarvis.dev.stages.planning import PlanningResult
from jarvis.dev.stages.requirements import RequirementsResult
from jarvis.dev.test_runner import (
    DevTestRequest,
    DebugReport,
    TestResult,
    analyze_static,
    diagnose,
    persist_report,
    run_tests,
    PROFILE_PYTEST,
    PROFILE_STATIC,
    STATUS_BLOCKED,
)
from jarvis.dev.workspace import DevWorkspace


@dataclass
class IntegrationReport:
    success: bool
    stages_completed: list[str] = field(default_factory=list)
    requirements: Optional[RequirementsResult] = None
    architecture: Optional[ArchitectureResult] = None
    planning: Optional[PlanningResult] = None
    generation: Optional[GenerationResult] = None
    static_analysis: Optional[TestResult] = None
    runtime_tests: Optional[TestResult] = None
    diagnosis: Optional[DebugReport] = None
    review_notes: list[str] = field(default_factory=list)
    documentation: str = ""
    qa_summary: str = ""
    error: Optional[str] = None
    limitations: list[str] = field(default_factory=list)
    execution_blocked: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "stages_completed": list(self.stages_completed),
            "error": self.error,
            "execution_blocked": self.execution_blocked,
            "qa_summary": self.qa_summary,
            "limitations": list(self.limitations),
            "review_notes": list(self.review_notes),
            "documentation": self.documentation,
            "static_status": self.static_analysis.status if self.static_analysis else None,
            "runtime_status": self.runtime_tests.status if self.runtime_tests else None,
            "code_executed": bool(
                self.runtime_tests and self.runtime_tests.code_executed
            ),
        }


def run_dev_workflow(
    user_request: str,
    workspace: DevWorkspace,
    *,
    project_id: Optional[str] = None,
    force_ready: bool = False,
) -> IntegrationReport:
    """Run the offline development workflow.

    Stages: requirements → architecture → planning → codegen → static analysis
    → diagnosis → review → documentation → QA report.

    Runtime execution is always BLOCKED in this phase.
    """
    report = IntegrationReport(success=False, execution_blocked=True)
    report.limitations.append(
        "Generated-code execution is BLOCKED: no verified OS isolation."
    )
    report.limitations.append(
        "Static analysis is syntax-only and is not runtime testing."
    )

    pipeline: PipelineResult = run_pipeline(
        user_request, project_id=project_id
    )
    report.requirements = pipeline.requirements
    if pipeline.error and not pipeline.requirements:
        report.error = pipeline.error
        return report
    if pipeline.requirements is None or pipeline.requirements.spec is None:
        report.error = pipeline.error or "requirements failed"
        return report
    report.stages_completed.append("requirements")

    spec = pipeline.requirements.spec
    unresolved = list(spec.clarifying_questions)
    if force_ready and spec.status != SPEC_READY:
        spec.status = SPEC_READY
        spec.clarifying_questions = []
        pipeline.requirements.complete = True
        if unresolved:
            report.limitations.append(
                "force_ready override used. Unresolved questions remain: "
                + "; ".join(unresolved)
            )
            report.review_notes.append(
                "OVERRIDE: force_ready cleared unresolved questions."
            )

    if not pipeline.requirements.complete and not force_ready:
        report.error = "Requirements incomplete; downstream stages stopped"
        report.qa_summary = "STOPPED: incomplete requirements"
        return report

    arch = design_architecture(spec)
    report.architecture = arch
    if not arch.success or arch.design is None:
        report.error = arch.error or "architecture failed"
        report.qa_summary = "STOPPED: architecture failed"
        return report
    report.stages_completed.append("architecture")

    from jarvis.dev.stages.planning import build_plan

    plan = build_plan(spec, arch.design)
    report.planning = plan
    if not plan.success or plan.plan is None:
        report.error = plan.error or "planning failed"
        report.qa_summary = "STOPPED: planning failed"
        return report
    report.stages_completed.append("planning")

    try:
        changes = propose_changes(spec, arch.design, plan.plan)
        prepared = prepare_generation(spec, arch.design, plan.plan, workspace, changes)
        if not prepared.prepared:
            report.generation = prepared
            report.error = prepared.error or "generation prepare failed"
            report.qa_summary = "STOPPED: generation prepare failed"
            return report
        applied = apply_generation(workspace, changes, prepared)
        report.generation = applied
        if not applied.success:
            report.error = applied.error or "generation apply failed"
            report.qa_summary = "STOPPED: generation apply failed"
            return report
    except Exception as exc:
        report.error = f"generation error: {exc}"
        note = " force_ready override was used." if any("force_ready override" in x for x in report.limitations) else ""
        report.qa_summary = f"STOPPED: generation exception.{note}"
        return report
    report.stages_completed.append("generation")

    # Static analysis only — never runtime
    related = [f.path for f in report.generation.files if f.status == "applied"]
    static = analyze_static(
        workspace,
        DevTestRequest(
            project_id=spec.project_id,
            profile=PROFILE_STATIC,
            related_files=related,
        ),
    )
    report.static_analysis = static
    report.stages_completed.append("static_analysis")

    # Explicitly request runtime and record BLOCKED
    runtime = run_tests(
        workspace,
        DevTestRequest(
            project_id=spec.project_id,
            profile=PROFILE_PYTEST,
            related_files=related,
        ),
    )
    report.runtime_tests = runtime
    report.stages_completed.append("runtime_status")
    if runtime.status != STATUS_BLOCKED or runtime.code_executed:
        report.error = "Runtime path must remain BLOCKED with no execution"
        report.qa_summary = "FAILED: execution policy violated"
        report.success = False
        return report

    diag = diagnose(static if static.status != "PASS" else runtime)
    report.diagnosis = diag
    report.stages_completed.append("diagnosis")

    report.review_notes = [
        f"Requirements status: {spec.status}",
        f"Plan tasks: {[i.task_id for i in plan.plan.items]}",
        f"Files applied: {related}",
        f"Static analysis: {static.status} (not runtime)",
        f"Runtime tests: {runtime.status} (code_executed={runtime.code_executed})",
    ]
    if static.status != "PASS":
        report.review_notes.append(
            f"Static finding: {static.failure_summary or static.reason}"
        )
    report.documentation = (
        f"# Offline development report\n\n"
        f"Request: {spec.user_request}\n\n"
        f"Static analysis: {static.status}.\n"
        f"Runtime tests: BLOCKED — no verified isolation.\n"
        f"Generated code was not executed.\n"
    )
    placeholder = False
    if report.generation and report.generation.files:
        for fr in report.generation.files:
            if fr.status == "applied":
                try:
                    text = workspace.read_text(fr.path)
                except Exception:
                    text = ""
                if "PLACEHOLDER = True" in text:
                    placeholder = True
                    break
    report.limitations.append(
        "Generated files are deterministic stubs. PLACEHOLDER=True means not a verified implementation."
        if placeholder else
        "No placeholder flag detected in applied files."
    )
    if static.status != "PASS":
        report.qa_summary = (
            f"STATIC ANALYSIS {static.status}: {static.failure_summary or static.reason}. "
            "This is not runtime testing. Runtime tests BLOCKED."
        )
        report.success = False
        report.error = report.qa_summary
    else:
        base = (
            "OFFLINE SCAFFOLD COMPLETE. PLACEHOLDER IMPLEMENTATION. "
            if placeholder else
            "OFFLINE WORKFLOW COMPLETE. "
        )
        if any("force_ready override" in x for x in report.limitations):
            base = "OFFLINE SCAFFOLD COMPLETE WITH OVERRIDE. "
        report.qa_summary = (
            base
            + "Runtime tests BLOCKED. Static analysis is not runtime testing. "
            + "Not a verified functional implementation."
        )
        # Placeholder-only deliverables are not reported as fully successful implementations.
        report.success = not placeholder
        if placeholder:
            report.error = "Placeholder-only generation; functional implementation not verified."
    report.stages_completed.append("review")
    report.stages_completed.append("documentation")
    report.stages_completed.append("qa")
    return report
