"""Gemini provider adapter — wraps existing GeminiClient."""

from __future__ import annotations

from typing import Any, Optional

from jarvis.ai.client import GeminiClient
from jarvis.ai.providers.base import AIProvider, ProviderCapabilities, ProviderResponse


class GeminiProvider:
    """Adapter around the Phase-1 GeminiClient.

    Does not hardcode API keys. Missing credentials mark the provider
    unavailable without crashing import or construction.
    """

    name = "gemini"
    mode = "LIVE"  # only when available and generate succeeds

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-flash",
        client: Optional[GeminiClient] = None,
    ) -> None:
        self.model = model_name
        self._client = client or GeminiClient(api_key=api_key, model_name=model_name)
        self.capabilities = ProviderCapabilities(
            text_generation=True,
            streaming=False,
            tools=False,
            vision=False,
            max_context_hint=None,
        )
        self._last_error: Optional[str] = self._client.last_error

    def available(self) -> bool:
        return bool(self._client.available)

    def last_error(self) -> Optional[str]:
        return self._last_error or self._client.last_error

    def generate(
        self,
        prompt: str,
        *,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        if not self.available():
            err = self.last_error() or "Gemini provider unavailable"
            self._last_error = err
            return ProviderResponse(
                text="",
                provider=self.name,
                model=self.model,
                success=False,
                error=err,
                mode="OFFLINE",
            )
        # GeminiClient.generate never raises on missing key; may return error string
        try:
            text = self._client.generate(prompt, **kwargs)
        except Exception as exc:
            self._last_error = str(exc)
            return ProviderResponse(
                text="",
                provider=self.name,
                model=self.model,
                success=False,
                error=str(exc),
                mode="LIVE",
            )
        if isinstance(text, str) and text.startswith("[AI unavailable]"):
            self._last_error = text
            return ProviderResponse(
                text="",
                provider=self.name,
                model=self.model,
                success=False,
                error=text,
                mode="OFFLINE",
            )
        if isinstance(text, str) and text.startswith("[AI error]"):
            self._last_error = text
            return ProviderResponse(
                text="",
                provider=self.name,
                model=self.model,
                success=False,
                error=text,
                mode="LIVE",
            )
        self._last_error = None
        return ProviderResponse(
            text=str(text),
            provider=self.name,
            model=self.model,
            success=True,
            mode="LIVE",
        )
