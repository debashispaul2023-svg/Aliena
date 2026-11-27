"""Specialised agent specs with permission boundaries + contract-checked dispatch."""

from __future__ import annotations

import time
from typing import Callable

from jarvis.creator.contracts import (AgentSpec, ContractError, Permission, TaskContract,
                                      TaskResult, TaskStatus)

P = Permission
_SPECS = [
    AgentSpec("architect", "Select stack and system structure", frozenset({P.READ_PROJECT, P.PROPOSE_ONLY}), 30, ("requirements",), ("design",)),
    AgentSpec("uiux_design", "Design layout, components and style guide", frozenset({P.PROPOSE_ONLY}), 30, ("requirements",), ("design",)),
    AgentSpec("frontend", "Frontend source files", frozenset({P.WRITE_NEW_WORKSPACE}), 60, ("design",), ("files",)),
    AgentSpec("backend", "Backend services and APIs", frozenset({P.WRITE_NEW_WORKSPACE}), 60, ("design",), ("files",)),
    AgentSpec("database", "Schema and data layer design", frozenset({P.WRITE_NEW_WORKSPACE}), 60, ("design",), ("files",)),
    AgentSpec("codegen", "Template-driven file generation", frozenset({P.WRITE_NEW_WORKSPACE}), 60, ("plan",), ("files",)),
    AgentSpec("testing", "Author tests; static checks only (no execution)", frozenset({P.WRITE_NEW_WORKSPACE, P.STATIC_ANALYSIS}), 60, ("files",), ("tests",)),
    AgentSpec("debugging", "Diagnose failures and propose fixes", frozenset({P.READ_PROJECT, P.PROPOSE_ONLY}), 60, ("failures",), ("proposals",)),
    AgentSpec("documentation", "README and technical docs", frozenset({P.WRITE_NEW_WORKSPACE}), 30, ("plan",), ("docs",)),
    AgentSpec("delivery", "Package and report delivery status", frozenset({P.READ_PROJECT}), 30, ("report",), ("summary",)),
]
FORBIDDEN_FOR_ALL = frozenset({P.EXECUTE_CODE, P.NETWORK})


class AgentDispatcher:
    def __init__(self) -> None:
        self.specs = {s.name: s for s in _SPECS}
        self._handlers: dict[str, Callable[[TaskContract], dict]] = {}

    def register(self, name: str, handler: Callable[[TaskContract], dict]) -> None:
        spec = self.specs[name]
        if spec.permissions & FORBIDDEN_FOR_ALL:
            raise ContractError("agent requests forbidden permission")
        self._handlers[name] = handler

    def dispatch(self, contract: TaskContract) -> TaskResult:
        spec = self.specs.get(contract.agent)
        if spec is None:
            return TaskResult(contract.task_id, contract.agent, TaskStatus.FAILED, error="unknown agent")
        try:
            contract.validate(spec)
        except ContractError as exc:
            return TaskResult(contract.task_id, contract.agent, TaskStatus.FAILED, error=str(exc))
        handler = self._handlers.get(contract.agent)
        if handler is None:
            return TaskResult(contract.task_id, contract.agent, TaskStatus.BLOCKED, error="agent not implemented in this phase")
        start = time.monotonic()
        try:
            out = handler(contract)
        except Exception as exc:  # agent errors never crash the engine
            return TaskResult(contract.task_id, contract.agent, TaskStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        if time.monotonic() - start > contract.timeout_seconds:
            return TaskResult(contract.task_id, contract.agent, TaskStatus.FAILED, error="timeout exceeded")
        missing = [k for k in spec.output_keys if k not in out]
        if missing:
            return TaskResult(contract.task_id, contract.agent, TaskStatus.FAILED, error=f"missing outputs {missing}")
        return TaskResult(contract.task_id, contract.agent, TaskStatus.DONE, outputs=out)
