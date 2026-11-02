"""AI package: client, providers, router, resource finder."""

from jarvis.ai.client import GeminiClient
from jarvis.ai.router import ProviderRouter, build_default_router, RouterResult
from jarvis.ai.resource_finder import ResourceFinder, ResourceFindResult, FixtureSearchAdapter

__all__ = [
    "GeminiClient",
    "ProviderRouter",
    "build_default_router",
    "RouterResult",
    "ResourceFinder",
    "ResourceFindResult",
    "FixtureSearchAdapter",
]
