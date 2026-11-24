"""Fail-closed execution policy. Host fallback is always rejected."""

from __future__ import annotations

from jarvis.dev.providers import ExecutionProvider, ExecutionRequest, ExecutionResult, SandboxCapability


REQUIRED = (
    "filesystem_isolation",
    "process_isolation",
    "privilege_separation",
    "network_restricted",
    "secret_isolation",
    "timeout",
    "cleanup",
)


class ExecutionPolicy:
    def evaluate(self, provider: ExecutionProvider, request: ExecutionRequest) -> ExecutionResult:
        audit = [{"stage": "verify_provider", "provider": provider.name, "state": provider.state}]
        if provider.state != "AVAILABLE" or not provider.healthy():
            return ExecutionResult(status="BLOCKED", executed=False, stderr="provider unavailable", audit=audit)
        caps = provider.capabilities()
        missing = [name for name in REQUIRED if not getattr(caps, name)]
        audit.append({"stage": "capabilities", "missing": missing})
        if missing:
            return ExecutionResult(status="BLOCKED", executed=False, stderr="isolation incomplete", audit=audit)
        return provider.execute(request)
