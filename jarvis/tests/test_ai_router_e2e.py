"""Router + orchestrator integration (OFFLINE / MOCKED)."""

from __future__ import annotations

from pathlib import Path

from jarvis.ai.router import ProviderRouter
from jarvis.ai.providers.deterministic import DeterministicProvider, MockProvider
from jarvis.ai.resource_finder import ResourceFinder, FixtureSearchAdapter
from jarvis.core.orchestrator import Orchestrator
from jarvis.core.models import STATUS_COMPLETED, STATUS_FAILED


def test_q_orchestrator_provider_routing(tmp_path: Path) -> None:
    det = DeterministicProvider()
    router = ProviderRouter(
        providers={"deterministic": det},
        preferred="deterministic",
        fallback=[],
        max_retries=0,
    )
    orch = Orchestrator(workspace=tmp_path / "ws", provider_router=router)
    # provider is available on context; simple run still works
    r = orch.run("offline job", simple=True, content="ok\n", record_experience=False)
    assert r.status == STATUS_COMPLETED
    assert orch.provider_router is router


def test_q_provider_failure_surface() -> None:
    bad = MockProvider(available_flag=False, error="no provider")
    router = ProviderRouter(
        providers={"mock": bad},
        preferred="mock",
        fallback=[],
        max_retries=0,
    )
    result = router.generate("hello", provider="mock", allow_fallback=False)
    assert result.response.success is False
    assert result.original_error or result.response.error


def test_s_regression_imports() -> None:
    from jarvis.ai.client import GeminiClient
    from jarvis.ai.router import build_default_router
    from jarvis.core import Orchestrator
    from jarvis.config import load_config

    c = GeminiClient(api_key=None)
    assert c.available is False
    r = build_default_router()
    assert "gemini" in r.list_providers() or "deterministic" in r.list_providers()
    assert load_config()["assistant_name"] == "Jarvis"


def test_offline_routing_chain(tmp_path: Path) -> None:
    primary = MockProvider(rate_limit=True, fail_times=99)
    fallback = DeterministicProvider()
    router = ProviderRouter(
        providers={"primary": primary, "deterministic": fallback},
        preferred="primary",
        fallback=["deterministic"],
        max_retries=1,
        retry_backoff_s=0,
    )
    result = router.generate("task text")
    assert result.fallback_used
    assert result.response.mode == "OFFLINE"
    assert result.response.success
    assert "[DETERMINISTIC OFFLINE]" in result.response.text
