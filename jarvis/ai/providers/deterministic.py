"""Deterministic offline provider for tests and no-key environments."""

from __future__ import annotations

from typing import Any, Optional

from jarvis.ai.providers.base import ProviderCapabilities, ProviderResponse


class DeterministicProvider:
    """Local fallback that never calls external APIs.

    Responses are clearly labelled so they cannot be mistaken for live AI.
    """

    name = "deterministic"
    mode = "OFFLINE"
    model = "deterministic-v1"

    def __init__(self, *, force_fail: bool = False, fail_times: int = 0) -> None:
        self.capabilities = ProviderCapabilities(text_generation=True)
        self._force_fail = force_fail
        self._fail_times = fail_times
        self._calls = 0
        self._last_error: Optional[str] = None

    def available(self) -> bool:
        return not self._force_fail or self._calls >= self._fail_times

    def last_error(self) -> Optional[str]:
        return self._last_error

    def generate(
        self,
        prompt: str,
        *,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        self._calls += 1
        if self._force_fail and self._calls <= self._fail_times:
            self._last_error = "Deterministic provider forced failure"
            return ProviderResponse(
                text="",
                provider=self.name,
                model=self.model,
                success=False,
                error=self._last_error,
                mode="OFFLINE",
            )
        # Echo a bounded, labelled summary — never claim to be a real model
        snippet = (prompt or "").strip().replace("\n", " ")[:120]
        text = f"[DETERMINISTIC OFFLINE] Acknowledged request ({len(prompt or '')} chars): {snippet}"
        self._last_error = None
        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self.model,
            success=True,
            mode="OFFLINE",
            metadata={"labelled_offline": True},
        )


class MockProvider:
    """Explicit test double. Results are MOCKED, never LIVE."""

    name = "mock"
    mode = "MOCKED"
    model = "mock-v1"

    def __init__(
        self,
        *,
        response_text: str = "mock response",
        available_flag: bool = True,
        error: Optional[str] = None,
        fail_times: int = 0,
        auth_error: bool = False,
        rate_limit: bool = False,
        timeout_error: bool = False,
        network_error: bool = False,
    ) -> None:
        self.capabilities = ProviderCapabilities(text_generation=True)
        self._response_text = response_text
        self._available_flag = available_flag
        self._error = error
        self._fail_times = fail_times
        self._calls = 0
        self._auth_error = auth_error
        self._rate_limit = rate_limit
        self._timeout_error = timeout_error
        self._network_error = network_error
        self._last_error: Optional[str] = error

    def available(self) -> bool:
        return self._available_flag and not self._auth_error

    def last_error(self) -> Optional[str]:
        return self._last_error

    def generate(
        self,
        prompt: str,
        *,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        self._calls += 1
        if self._auth_error:
            self._last_error = "Authentication failed: invalid API key"
            return ProviderResponse(
                text="", provider=self.name, model=self.model, success=False,
                error=self._last_error, mode="MOCKED",
            )
        if self._rate_limit and self._calls <= self._fail_times:
            self._last_error = "Rate limit exceeded (429)"
            return ProviderResponse(
                text="", provider=self.name, model=self.model, success=False,
                error=self._last_error, mode="MOCKED",
            )
        if self._timeout_error and self._calls <= self._fail_times:
            self._last_error = "Request timed out"
            return ProviderResponse(
                text="", provider=self.name, model=self.model, success=False,
                error=self._last_error, mode="MOCKED",
            )
        if self._network_error and self._calls <= self._fail_times:
            self._last_error = "Network error: connection refused"
            return ProviderResponse(
                text="", provider=self.name, model=self.model, success=False,
                error=self._last_error, mode="MOCKED",
            )
        if not self._available_flag:
            self._last_error = self._error or "Mock provider unavailable"
            return ProviderResponse(
                text="", provider=self.name, model=self.model, success=False,
                error=self._last_error, mode="MOCKED",
            )
        self._last_error = None
        return ProviderResponse(
            text=self._response_text,
            provider=self.name,
            model=self.model,
            success=True,
            mode="MOCKED",
        )
