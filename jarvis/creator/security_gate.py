"""Central SecurityGate. Single choke point for every Creator action.

* Code execution is ALWAYS blocked in C1 (Phase 6F BLOCKED). User approval cannot
  unlock it; there is no host fallback.
* Approval-controlled actions need a matching ApprovalDecision bound to the action.
* Unknown actions are denied (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from jarvis.core.approval import ApprovalDecision
from jarvis.creator.audit import AuditLogger

AUTOMATIC = frozenset({
    "plan", "create_workspace", "write_generated_file", "static_analysis",
    "inspect_source", "propose_fix", "generate_docs",
    "generate_project_files", "discard_generation_output", "correct_generated_file",
    "run_static_checks", "generate_tests",
})
APPROVAL_REQUIRED = frozenset({
    "install_dependencies", "external_download", "modify_existing_project",
    "overwrite_file", "delete_file", "access_credentials", "network_action",
    "publish", "deploy", "os_action", "export_delivery",
})
ALWAYS_BLOCKED = frozenset({
    "execute_code", "run_generated_script", "run_downloaded_code", "run_plugin",
    "workspace_escape",
})


@dataclass(frozen=True)
class GateDecision:
    action: str
    allowed: bool
    reason: str
    needs_approval: bool = False


class SecurityGate:
    def __init__(self, audit: AuditLogger) -> None:
        self._audit = audit

    def check(self, project_id: str, actor: str, action: str,
              approval: Optional[ApprovalDecision] = None) -> GateDecision:
        if action in ALWAYS_BLOCKED:
            d = GateDecision(action, False, "execution BLOCKED: OS isolation not verified (Phase 6F)")
        elif action in AUTOMATIC:
            d = GateDecision(action, True, "automatic safe action")
        elif action in APPROVAL_REQUIRED:
            if approval is not None and approval.allows(action) and getattr(approval, "target", None) in (None, "", project_id):
                d = GateDecision(action, True, "approved")
            else:
                d = GateDecision(action, False, "approval required", needs_approval=True)
        else:
            d = GateDecision(action, False, "unknown action denied")
        self._audit.record(project_id, actor, action, "allowed" if d.allowed else "denied", d.reason)
        return d
