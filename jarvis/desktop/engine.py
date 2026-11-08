"""Desktop Automation Engine — permission, approval, validation, then controller."""

from __future__ import annotations

from typing import Any

from jarvis.desktop.approval import ApprovalManager
from jarvis.desktop.audit import AuditLogger
from jarvis.desktop.controller import DesktopController
from jarvis.desktop.permissions import PermissionManager
from jarvis.desktop.validator import ActionRequest, ActionValidator


class DesktopAutomationEngine:
    def __init__(
        self,
        controller: DesktopController | None = None,
        permissions: PermissionManager | None = None,
        approvals: ApprovalManager | None = None,
        validator: ActionValidator | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self.audit = audit or AuditLogger()
        self.controller = controller or DesktopController(audit=self.audit)
        self.permissions = permissions or PermissionManager()
        self.approvals = approvals or ApprovalManager()
        self.validator = validator or ActionValidator()

    def grant(self, action: str) -> None:
        self.permissions.grant(action)

    def approve(self, action: str, *, reviewer: str = "user") -> None:
        self.approvals.request(action, reviewer=reviewer, approved=True)

    def cancel(self) -> dict[str, Any]:
        return self.controller.cancel()

    def run(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if action in {"detect_environment", "list_capabilities", "cancel"}:
            result = self.controller.execute(action, params)
            self.audit.record(action, result.get("status", "UNKNOWN"))
            return result
        try:
            self.permissions.require(action)
        except PermissionError as exc:
            self.audit.record(action, "PERMISSION_DENIED", detail=str(exc))
            return {"ok": False, "status": "PERMISSION_DENIED", "executed": False}
        approved = self.approvals.is_approved(action)
        request = ActionRequest(action=action, params=params, approved=approved)
        try:
            self.validator.validate(request)
        except (ValueError, PermissionError) as exc:
            status = "APPROVAL_REQUIRED" if "approval" in str(exc).lower() else "INVALID"
            self.audit.record(action, status, detail=str(exc))
            return {"ok": False, "status": status, "executed": False, "reason": str(exc)}
        result = self.controller.execute(action, params)
        self.audit.record(action, result.get("status", "UNKNOWN"), detail=str(result.get("reason", "")))
        return result
