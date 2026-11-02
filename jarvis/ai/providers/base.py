"""Provider interface for AI text generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    success: bool = True
    error: Optional[str] = None
    mode: str = "OFFLINE"  # MOCKED | OFFLINE | LIVE
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderCapabilities:
    text_generation: bool = True
    streaming: bool = False
    tools: bool = False
    vision: bool = False
    max_context_hint: Optional[int] = None  # never invent; leave None if unknown


class AIProvider(Protocol):
    name: str
    model: str
    mode: str
    capabilities: ProviderCapabilities

    def available(self) -> bool: ...

    def last_error(self) -> Optional[str]: ...

    def generate(
        self,
        prompt: str,
        *,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> ProviderResponse: ...
