"""AI Provider Router — selection, retries, explicit fallback."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.ai.circuit import CircuitBreaker
from jarvis.ai.providers.base import ProviderResponse
from jarvis.ai.providers.gemini import GeminiProvider
from jarvis.ai.providers.deterministic import DeterministicProvider


# Errors that should not be retried
NON_RETRYABLE = (
    "authentication",
    "invalid api key",
    "api key",
    "unauthorized",
    "permission",
    "not installed",
    "unavailable",
    "unsupported",
)


@dataclass
class RouterResult:
    response: ProviderResponse
    selected_provider: str
    attempted: list[str] = field(default_factory=list)
    fallback_used: bool = False
    original_error: Optional[str] = None


class ProviderRouter:
    """Selects and invokes AI providers according to policy.

    Configuration (env / constructor):
      JARVIS_AI_PROVIDER   preferred provider name (e.g. gemini, deterministic)
      JARVIS_AI_FALLBACK   comma-separated fallback chain (default: deterministic)
      JARVIS_AI_MAX_RETRIES  bounded retries for transient failures (default 2)

    Never logs or returns API keys. Missing credentials do not crash import.
    """

    def __init__(
        self,
        providers: Optional[dict[str, Any]] = None,
        preferred: Optional[str] = None,
        fallback: Optional[list[str]] = None,
        max_retries: int = 2,
        retry_backoff_s: float = 0.0,  # 0 for fast tests
    ) -> None:
        self._providers: dict[str, Any] = {}
        if providers is not None:
            for name, p in providers.items():
                self._providers[name] = p
        else:
            self._providers["gemini"] = GeminiProvider()
            self._providers["deterministic"] = DeterministicProvider()

        self.preferred = (
            preferred
            or os.environ.get("JARVIS_AI_PROVIDER")
            or "gemini"
        ).strip().lower()
        fb_env = os.environ.get("JARVIS_AI_FALLBACK", "deterministic")
        self.fallback = fallback or [x.strip() for x in fb_env.split(",") if x.strip()]
        try:
            env_retries = int(os.environ.get("JARVIS_AI_MAX_RETRIES", str(max_retries)))
        except ValueError:
            env_retries = max_retries
        self.max_retries = max(0, env_retries)
        self.retry_backoff_s = max(0.0, retry_backoff_s)
        self.circuits: dict[str, CircuitBreaker] = {}

    def circuit(self, name: str) -> CircuitBreaker:
        if name not in self.circuits:
            self.circuits[name] = CircuitBreaker()
        return self.circuits[name]

    def register(self, provider: Any) -> None:
        self._providers[provider.name] = provider

    def list_providers(self) -> list[str]:
        return sorted(self._providers.keys())

    def get(self, name: str) -> Any:
        if name not in self._providers:
            raise KeyError(f"Unknown provider: {name}")
        return self._providers[name]

    def select(
        self,
        *,
        explicit: Optional[str] = None,
        require_text: bool = True,
        prefer_available: bool = True,
    ) -> str:
        """Choose a provider name. Does not invent capabilities."""
        if explicit:
            name = explicit.strip().lower()
            if name not in self._providers:
                raise KeyError(f"Unknown provider: {name}")
            return name

        candidates = [self.preferred] + [f for f in self.fallback if f != self.preferred]
        for name in candidates:
            p = self._providers.get(name)
            if p is None:
                continue
            caps = getattr(p, "capabilities", None)
            if require_text and caps is not None and not getattr(caps, "text_generation", True):
                continue
            if prefer_available and hasattr(p, "available") and not p.available():
                continue
            return name
        # Last resort: any registered provider name even if unavailable
        if self.preferred in self._providers:
            return self.preferred
        if self._providers:
            return next(iter(self._providers))
        raise RuntimeError("No AI providers registered")

    def _is_retryable(self, error: Optional[str]) -> bool:
        if not error:
            return False
        low = error.lower()
        for token in NON_RETRYABLE:
            if token in low:
                return False
        # transient-ish
        return any(
            t in low
            for t in ("rate limit", "429", "timeout", "timed out", "network", "connection", "temporary", "forced failure")
        )

    def generate(
        self,
        prompt: str,
        *,
        provider: Optional[str] = None,
        allow_fallback: bool = True,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> RouterResult:
        """Generate text with selection, bounded retries, and explicit fallback.

        Fallback preserves the original provider error in RouterResult.original_error.
        Deterministic/mocked responses are labelled in response.mode.
        """
        attempted: list[str] = []
        original_error: Optional[str] = None

        if provider:
            try:
                primary = self.select(explicit=provider)
            except (KeyError, RuntimeError) as exc:
                return RouterResult(
                    response=ProviderResponse(
                        text="",
                        provider="none",
                        model="",
                        success=False,
                        error=str(exc),
                        mode="OFFLINE",
                    ),
                    selected_provider="none",
                    attempted=[],
                    fallback_used=False,
                    original_error=str(exc),
                )
        else:
            # Try preferred first even if currently unavailable, so failures are visible
            if self.preferred in self._providers:
                primary = self.preferred
            else:
                try:
                    primary = self.select()
                except (KeyError, RuntimeError) as exc:
                    return RouterResult(
                        response=ProviderResponse(
                            text="",
                            provider="none",
                            model="",
                            success=False,
                            error=str(exc),
                            mode="OFFLINE",
                        ),
                        selected_provider="none",
                        attempted=[],
                        fallback_used=False,
                        original_error=str(exc),
                    )

        chain = [primary]
        if allow_fallback:
            for fb in self.fallback:
                if fb not in chain and fb in self._providers:
                    chain.append(fb)

        last_response: Optional[ProviderResponse] = None
        for idx, name in enumerate(chain):
            p = self._providers[name]
            attempted.append(name)
            retries = 0
            while True:
                resp = p.generate(prompt, timeout=timeout, **kwargs)
                last_response = resp
                if resp.success:
                    self.circuit(name).record_success()
                    return RouterResult(
                        response=resp,
                        selected_provider=name,
                        attempted=attempted,
                        fallback_used=idx > 0,
                        original_error=original_error,
                    )
                # failure
                if original_error is None:
                    original_error = resp.error
                if retries < self.max_retries and self._is_retryable(resp.error):
                    retries += 1
                    if self.retry_backoff_s:
                        time.sleep(self.retry_backoff_s)
                    continue
                self.circuit(name).record_failure()
                break  # move to next provider in chain

        # All failed
        err = original_error or (last_response.error if last_response else "All providers failed")
        return RouterResult(
            response=ProviderResponse(
                text="",
                provider=attempted[-1] if attempted else "none",
                model=getattr(last_response, "model", "") if last_response else "",
                success=False,
                error=err,
                mode=getattr(last_response, "mode", "OFFLINE") if last_response else "OFFLINE",
            ),
            selected_provider=attempted[-1] if attempted else "none",
            attempted=attempted,
            fallback_used=len(attempted) > 1,
            original_error=original_error,
        )


def build_default_router() -> ProviderRouter:
    return ProviderRouter()
