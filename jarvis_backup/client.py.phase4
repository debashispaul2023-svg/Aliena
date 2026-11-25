"""AI client abstraction (Phase 1: Gemini only).

Wraps google.generativeai so the rest of the application does not
call the SDK directly. Missing API key is handled gracefully:
the client reports itself as unavailable and generate() returns
a clear error string instead of exiting the process.
"""

from __future__ import annotations

import os
from typing import Any, Optional

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover
    genai = None  # type: ignore


class GeminiClient:
    """Thin wrapper around the Gemini GenerativeModel used by Jarvis."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-flash",
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self._model: Any = None
        self.available = False
        self.last_error: Optional[str] = None

        if genai is None:
            self.last_error = "google-generativeai package is not installed"
            return
        if not self.api_key:
            self.last_error = "GEMINI_API_KEY environment variable is not set"
            return

        try:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(model_name)
            self.available = True
        except Exception as exc:  # pragma: no cover - network/key errors
            self.last_error = str(exc)
            self.available = False

    def generate(self, prompt: str | list, **kwargs: Any) -> str:
        """Generate content. Returns a string. Never raises on missing key.

        If the client is unavailable, returns a user-friendly error message
        so callers can speak it or log it without crashing.
        """
        if not self.available or self._model is None:
            return (
                f"[AI unavailable] {self.last_error or 'Gemini client is not ready.'} "
                "Set the GEMINI_API_KEY environment variable to enable AI features."
            )
        try:
            response = self._model.generate_content(prompt, **kwargs)
            text = getattr(response, "text", None)
            if text is None:
                return "[AI error] Empty response from model."
            return str(text)
        except Exception as exc:
            return f"[AI error] {exc}"

    def generate_content(self, prompt: str | list, **kwargs: Any) -> Any:
        """Compatibility shim that mimics the original model.generate_content().

        Returns an object with a .text attribute so existing call sites
        that do response.text keep working after a one-line swap.
        """
        text = self.generate(prompt, **kwargs)

        class _Response:
            def __init__(self, t: str) -> None:
                self.text = t

        return _Response(text)


def get_default_client() -> GeminiClient:
    """Convenience factory used by the application entry point."""
    return GeminiClient()
