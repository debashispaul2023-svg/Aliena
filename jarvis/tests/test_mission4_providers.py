"""Mission 4 provider tests. Mocks prove fail-closed behavior, not isolation."""

from jarvis.dev.execution_policy import ExecutionPolicy
from jarvis.dev.providers import ExecutionProvider, ExecutionRequest, SandboxCapability


class UnavailableProvider(ExecutionProvider):
    name = "none"
    state = "UNAVAILABLE"


class UnverifiedProvider(ExecutionProvider):
    name = "unshare"
    state = "UNVERIFIED"

    def healthy(self) -> bool:
        return True


class CompleteProvider(ExecutionProvider):
    name = "test-sandbox"
    state = "AVAILABLE"

    def healthy(self) -> bool:
        return True

    def capabilities(self) -> SandboxCapability:
        return SandboxCapability(
            filesystem_isolation=True,
            process_isolation=True,
            privilege_separation=True,
            network_restricted=True,
            secret_isolation=True,
            timeout=True,
            cleanup=True,
        )


def test_unavailable_blocked():
    result = ExecutionPolicy().evaluate(UnavailableProvider(), ExecutionRequest(["python", "app.py"], "ws"))
    assert result.status == "BLOCKED"
    assert result.executed is False


def test_unverified_blocked():
    result = ExecutionPolicy().evaluate(UnverifiedProvider(), ExecutionRequest(["python", "app.py"], "ws"))
    assert result.status == "BLOCKED"


def test_verified_provider_still_not_host_fallback():
    result = ExecutionPolicy().evaluate(CompleteProvider(), ExecutionRequest(["python", "app.py"], "ws"))
    assert result.executed is False
    assert result.status == "BLOCKED"
