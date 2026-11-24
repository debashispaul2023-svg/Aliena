"""Safe execution gate. Refuses host execution until isolation is verified."""

from __future__ import annotations


class IsolationNotVerified(RuntimeError):
    pass


class ExecutionGate:
    def __init__(self, *, isolated: bool = False) -> None:
        self.isolated = isolated

    def run(self, command: list[str]) -> dict:
        if not self.isolated:
            raise IsolationNotVerified("Phase 6F BLOCKED: isolation not verified")
        return {"status": "BLOCKED", "executed": False, "command": command}
