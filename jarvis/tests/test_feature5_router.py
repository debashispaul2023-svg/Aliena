"""Feature 5 router tests. Mocked providers only."""

from __future__ import annotations

from jarvis.ai.router import ProviderRouter
from jarvis.ai.providers.deterministic import MockProvider, DeterministicProvider


def test_fallback_on_timeout():
    flaky = MockProvider(timeout_error=True, fail_times=99)
    det = DeterministicProvider()
    router = ProviderRouter(
        providers={"flaky": flaky, "deterministic": det},
        preferred="flaky",
        fallback=["deterministic"],
        max_retries=1,
    )
    result = router.generate("hello")
    assert result.response.success
    assert result.fallback_used
    assert "deterministic" in result.attempted


def test_auth_error_not_retried_forever():
    auth = MockProvider(auth_error=True)
    router = ProviderRouter(
        providers={"auth": auth},
        preferred="auth",
        fallback=[],
        max_retries=5,
    )
    result = router.generate("hello")
    assert result.response.success is False
    assert "api key" in (result.response.error or "").lower()


def test_circuit_opens_after_failures():
    flaky = MockProvider(network_error=True, fail_times=99)
    router = ProviderRouter(
        providers={"flaky": flaky},
        preferred="flaky",
        fallback=[],
        max_retries=0,
    )
    router.generate("a")
    router.generate("b")
    router.generate("c")
    assert router.circuit("flaky").open is True
    blocked = router.generate("d")
    assert blocked.response.success is False


def test_secret_not_in_error():
    key = "sk-live-secret-value"
    provider = MockProvider(auth_error=True)
    router = ProviderRouter(
        providers={"bad": provider},
        preferred="bad",
        fallback=[],
        max_retries=0,
    )
    result = router.generate("hello")
    assert key not in str(result)
    assert "GEMINI_API_KEY" not in str(result)
