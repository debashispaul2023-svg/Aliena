"""Router provider + legacy-compatible client backed by the multi-account manager.

Used only when at least one GEMINI_API_KEY_1..3 variable is set; otherwise the original single-key
GeminiProvider/GeminiClient are used exactly as before."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from jarvis.ai.gemini_accounts import (GeminiAccountManager, shared_manager, slot_keys_configured)
from jarvis.ai.providers.base import ProviderCapabilities, ProviderResponse
from jarvis.core.redaction import redact_secrets


class GeminiMultiAccountProvider:
    name = "gemini"
    mode = "LIVE"

    def __init__(self, manager: Optional[GeminiAccountManager] = None) -> None:
        self.manager = manager or shared_manager()
        self.capabilities = ProviderCapabilities(text_generation=True, streaming=False, tools=False, vision=False, max_context_hint=None)

    @property
    def model(self) -> str:
        return self.manager.model

    def available(self) -> bool:
        return self.manager.available()

    def last_error(self) -> Optional[str]:
        return self.manager.last_error()

    def generate(self, prompt: Any, *, timeout: Optional[float] = None, **kwargs: Any) -> ProviderResponse:
        res = self.manager.generate(prompt, timeout=timeout, **kwargs)
        meta = {"slot": res.slot, "attempts": res.attempts, "retries": res.retries}
        if res.ok:
            return ProviderResponse(text=res.text, provider=self.name, model=res.model or self.model, success=True,
                                    mode="LIVE", usage=dict(res.usage), metadata=meta)
        # LIVE only if a real request was actually attempted; otherwise the provider never reached Google
        return ProviderResponse(text="", provider=self.name, model=res.model or self.model, success=False,
                                error=redact_secrets(res.error or "Gemini unavailable"),
                                mode="LIVE" if res.network_attempted else "OFFLINE", usage=dict(res.usage),
                                metadata={**meta, "category": res.category, "cooldown_s": res.cooldown_s})


def make_default_gemini_provider(env: Optional[Mapping[str, str]] = None, **manager_kwargs: Any) -> Any:
    """Multi-account provider when any slot key is set; otherwise the original GeminiProvider (unchanged)."""
    if slot_keys_configured(env):
        if env is None and not manager_kwargs:
            return GeminiMultiAccountProvider(shared_manager())
        return GeminiMultiAccountProvider(GeminiAccountManager(env=env, **manager_kwargs))
    from jarvis.ai.providers.gemini import GeminiProvider
    return GeminiProvider()


class AccountGeminiClient:
    """Drop-in for jarvis.ai.client.GeminiClient (same generate()/generate_content() contract and message
    prefixes) that goes through the account manager. Exposes no key attribute."""

    def __init__(self, manager: Optional[GeminiAccountManager] = None) -> None:
        self.manager = manager or shared_manager()

    @property
    def model_name(self) -> str:
        return self.manager.model

    @property
    def available(self) -> bool:
        return self.manager.active_slot is not None and not self.manager.health()["overall"] == "blocked"

    @property
    def last_error(self) -> Optional[str]:
        return self.manager.last_error()

    def generate(self, prompt: Any, **kwargs: Any) -> str:
        res = self.manager.generate(prompt, **{k: v for k, v in kwargs.items() if k != "timeout"}, timeout=kwargs.get("timeout"))
        if res.ok:
            return res.text
        if not res.network_attempted:
            return f"[AI unavailable] {res.error} Configure GEMINI_API_KEY_1..3 and check them in Gemini settings."
        return f"[AI error] {res.error}"

    def generate_content(self, prompt: Any, **kwargs: Any) -> Any:
        text = self.generate(prompt, **kwargs)

        class _Response:
            def __init__(self, t: str) -> None:
                self.text = t

        return _Response(text)


def build_account_client_if_configured(env: Optional[Mapping[str, str]] = None) -> Optional[AccountGeminiClient]:
    return AccountGeminiClient() if slot_keys_configured(env) else None
