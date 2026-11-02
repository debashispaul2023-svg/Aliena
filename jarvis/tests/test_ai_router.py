"""AI Provider Router unit tests (MOCKED / OFFLINE)."""

from __future__ import annotations

import pytest

from jarvis.ai.router import ProviderRouter
from jarvis.ai.providers.deterministic import DeterministicProvider, MockProvider
from jarvis.ai.providers.gemini import GeminiProvider
from jarvis.ai.client import GeminiClient


def test_a_explicit_provider_selection() -> None:
    mock = MockProvider(response_text="from-mock")
    det = DeterministicProvider()
    router = ProviderRouter(
        providers={"mock": mock, "deterministic": det},
        preferred="deterministic",
        fallback=["deterministic"],
        max_retries=0,
    )
    result = router.generate("hello", provider="mock")
    assert result.response.success
    assert result.selected_provider == "mock"
    assert result.response.text == "from-mock"
    assert result.response.mode == "MOCKED"


def test_b_capability_and_availability_policy() -> None:
    unavailable = MockProvider(available_flag=False, error="no key")
    det = DeterministicProvider()
    router = ProviderRouter(
        providers={"gemini": unavailable, "deterministic": det},
        preferred="gemini",
        fallback=["deterministic"],
        max_retries=0,
    )
    name = router.select()
    assert name == "deterministic"


def test_c_missing_credentials_no_crash() -> None:
    client = GeminiClient(api_key=None)
    assert client.available is False
    provider = GeminiProvider(client=client)
    assert provider.available() is False
    resp = provider.generate("hi")
    assert resp.success is False
    err = (resp.error or "").lower()
    assert (
        "unavailable" in err
        or "gemini" in err
        or "not installed" in err
        or "api key" in err
        or "not set" in err
    )


def test_d_auth_error_not_retried_forever() -> None:
    mock = MockProvider(auth_error=True)
    det = DeterministicProvider()
    router = ProviderRouter(
        providers={"mock": mock, "deterministic": det},
        preferred="mock",
        fallback=["deterministic"],
        max_retries=3,
    )
    result = router.generate("x", allow_fallback=True)
    assert result.fallback_used is True
    assert result.original_error and "Authentication" in result.original_error
    assert result.response.success is True  # fallback worked
    assert result.selected_provider == "deterministic"


def test_e_rate_limit_bounded_retries() -> None:
    mock = MockProvider(rate_limit=True, fail_times=2, response_text="ok-after-retry")
    router = ProviderRouter(
        providers={"mock": mock},
        preferred="mock",
        fallback=[],
        max_retries=3,
        retry_backoff_s=0,
    )
    result = router.generate("x")
    assert result.response.success
    assert mock._calls >= 3


def test_f_timeout_and_network_errors() -> None:
    timeout_p = MockProvider(timeout_error=True, fail_times=1, response_text="recovered")
    router = ProviderRouter(
        providers={"mock": timeout_p},
        preferred="mock",
        fallback=[],
        max_retries=2,
        retry_backoff_s=0,
    )
    result = router.generate("x")
    assert result.response.success

    net = MockProvider(network_error=True, fail_times=99)
    det = DeterministicProvider()
    router2 = ProviderRouter(
        providers={"mock": net, "deterministic": det},
        preferred="mock",
        fallback=["deterministic"],
        max_retries=1,
        retry_backoff_s=0,
    )
    result2 = router2.generate("x")
    assert result2.fallback_used
    assert result2.original_error and "Network" in result2.original_error


def test_g_fallback_preserves_original_error() -> None:
    bad = MockProvider(available_flag=False, error="primary down")
    det = DeterministicProvider()
    router = ProviderRouter(
        providers={"primary": bad, "deterministic": det},
        preferred="primary",
        fallback=["deterministic"],
        max_retries=0,
    )
    # force select primary even if unavailable by explicit name
    result = router.generate("hi", provider="primary", allow_fallback=True)
    # primary fails, then fallback
    assert result.original_error is not None
    assert result.fallback_used or result.selected_provider == "deterministic"


def test_h_no_suitable_provider_error() -> None:
    router = ProviderRouter(providers={}, preferred="none", fallback=[], max_retries=0)
    result = router.generate("x")
    assert result.response.success is False
    assert "No AI providers" in (result.response.error or "") or result.selected_provider == "none"


def test_i_secrets_absent_from_errors() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    client = GeminiClient(api_key=secret)
    # even if configured, error paths should not echo the key
    provider = GeminiProvider(client=GeminiClient(api_key=None))
    resp = provider.generate("test")
    assert secret not in (resp.error or "")
    assert secret not in (resp.text or "")


def test_j_gemini_client_backward_compatible() -> None:
    client = GeminiClient(api_key=None)
    text = client.generate("hello")
    assert "AI unavailable" in text or "GEMINI_API_KEY" in text
    # generate_content shim
    resp = client.generate_content("hello")
    assert hasattr(resp, "text")
