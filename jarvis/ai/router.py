"""AI Provider Router — selection, retries, explicit fallback."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.ai.circuit import CircuitBreaker
from jarvis.ai.providers.base import ProviderResponse
from jarvis.ai.providers.gemini import GeminiProvider
from jarvis.ai.providers.deterministic import DeterministicProvider
from jarvis.core.redaction import redact_secrets


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


# Extra seconds the router waits beyond ``timeout`` so providers that honour the
# timeout themselves can return their own (more specific) error first.
_TIMEOUT_GRACE_S = 0.25
_MAX_ERROR_CHARS = 300


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
            # Multi-account provider only when a GEMINI_API_KEY_1..3 variable is set; otherwise the original provider.
            from jarvis.ai.providers.gemini_multi import make_default_gemini_provider

            self._providers["gemini"] = make_default_gemini_provider()
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

    def _failure(self, name: str, error: str, **metadata: Any) -> ProviderResponse:
        return ProviderResponse(
            text="",
            provider=name,
            model="",
            success=False,
            error=redact_secrets(error)[:_MAX_ERROR_CHARS],
            mode="OFFLINE",
            metadata=dict(metadata),
        )

    def _invoke(self, name: str, provider: Any, prompt: str, timeout: Optional[float], kwargs: dict[str, Any]) -> ProviderResponse:
        """Call one provider and ALWAYS return a ProviderResponse.

        * exceptions become failed responses (message passed through the redactor)
        * a malformed return value (None, dict, ...) becomes a failed response
        * when ``timeout`` is set it is enforced here, not only passed through; a
          provider that hangs is abandoned (daemon thread) and reported as timed out
        """
        try:
            if timeout is None or timeout <= 0:
                resp = provider.generate(prompt, timeout=timeout, **kwargs)
            else:
                box: dict[str, Any] = {}

                def runner() -> None:
                    try:
                        box["resp"] = provider.generate(prompt, timeout=timeout, **kwargs)
                    except Exception as exc:  # reported below
                        box["exc"] = exc

                worker = threading.Thread(target=runner, name=f"router-{name}", daemon=True)
                worker.start()
                worker.join(timeout + _TIMEOUT_GRACE_S)
                if worker.is_alive():
                    return self._failure(
                        name, f"provider timed out after {timeout}s (enforced by router)", router_timeout=True
                    )
                if "exc" in box:
                    raise box["exc"]
                resp = box.get("resp")
        except Exception as exc:
            return self._failure(name, f"provider raised {type(exc).__name__}: {exc}")
        if resp is None or not hasattr(resp, "success") or not hasattr(resp, "text"):
            return self._failure(name, f"provider returned invalid response type: {type(resp).__name__}")
        if not resp.success and getattr(resp, "error", None):
            resp.error = redact_secrets(resp.error)
        return resp

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
            if not self.circuit(name).allow():
                # Open circuit: skip this provider (it is retried after the cooldown).
                if original_error is None:
                    original_error = f"circuit open for provider: {name}"
                continue
            attempted.append(name)
            retries = 0
            while True:
                resp = self._invoke(name, p, prompt, timeout, kwargs)
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
                router_timed_out = bool(getattr(resp, "metadata", None) and resp.metadata.get("router_timeout"))
                if not router_timed_out and retries < self.max_retries and self._is_retryable(resp.error):
                    retries += 1
                    if self.retry_backoff_s:
                        time.sleep(self.retry_backoff_s)
                    continue
                self.circuit(name).record_failure()
                break  # move to next provider in chain

        # All failed (or every provider's circuit was open)
        err = original_error or (last_response.error if last_response else "All providers failed")
        if not attempted:
            err = f"{err}; no provider available (all circuits open)" if err else "no provider available (all circuits open)"
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
