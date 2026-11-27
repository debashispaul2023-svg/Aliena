"""RequirementAnalyzer: project-type detection layered on the 6C requirements stage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.creator.contracts import ProjectType, StackSelection
from jarvis.creator.stacks import detect_project_type, select_stack


@dataclass
class TypeAnalysis:
    project_type: ProjectType
    stack: StackSelection
    context: dict[str, Any]
    assumption: str


class RequirementAnalyzer:
    def analyze(self, user_request: str) -> TypeAnalysis:
        ptype = detect_project_type(user_request)
        stack = select_stack(ptype)
        ctx: dict[str, Any] = {}
        note = f"Assumption: project type '{ptype.value}' inferred from keywords (offline heuristic, confirm)."
        if stack.languages:
            # Only suppress the generic language question when the request itself
            # implies a stack; the inference is recorded as an assumption, never as confirmed.
            ctx["language"] = "/".join(stack.languages)
            note += f" Stack: {', '.join(stack.languages + stack.frameworks)}."
        return TypeAnalysis(ptype, stack, ctx, note)
