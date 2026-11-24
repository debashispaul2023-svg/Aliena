"""Execution provider models. Architecture only. Isolation is not claimed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ProviderState = Literal["AVAILABLE", "UNAVAILABLE", "UNVERIFIED", "BLOCKED", "CONFIGURATION_REQUIRED"]


@dataclass
class SandboxCapability:
    filesystem_isolation: bool = False
    process_isolation: bool = False
    privilege_separation: bool = False
    network_restricted: bool = False
    secret_isolation: bool = False
    timeout: bool = False
    cleanup: bool = False


@dataclass
class ExecutionRequest:
    command: list[str]
    workspace: str
    timeout_seconds: int = 10


@dataclass
class ExecutionResult:
    status: str
    executed: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    audit: list[dict] = field(default_factory=list)


class ExecutionProvider:
    name = "base"
    state: ProviderState = "UNVERIFIED"

    def capabilities(self) -> SandboxCapability:
        return SandboxCapability()

    def healthy(self) -> bool:
        return False

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(status="BLOCKED", executed=False, stderr="provider not verified")
