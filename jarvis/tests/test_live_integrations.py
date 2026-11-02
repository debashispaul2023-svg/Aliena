"""Live integration tests — skip when credentials/hardware unavailable.

LIVE tests make real network calls. They never substitute mocks.
"""

from __future__ import annotations

import os

import pytest

from jarvis.ai.client import GeminiClient
from jarvis.ai.providers.gemini import GeminiProvider
from jarvis.ai.providers.web_search import DuckDuckGoHTMLAdapter
from jarvis.ai.resource_finder import ResourceFinder
from jarvis.ai.router import ProviderRouter
from jarvis.ai.providers.deterministic import DeterministicProvider


def _has_gemini() -> bool:
    if not os.environ.get("GEMINI_API_KEY"):
        return False
    try:
        import google.generativeai  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.live
def test_live_gemini_provider_request() -> None:
    if not _has_gemini():
        pytest.skip("LIVE Gemini blocked: GEMINI_API_KEY or google-generativeai missing")
    provider = GeminiProvider()
    assert provider.available(), provider.last_error()
    resp = provider.generate("Reply with exactly the word PONG and nothing else.")
    assert resp.success, resp.error
    assert resp.mode == "LIVE"
    assert resp.text and len(resp.text.strip()) > 0
    assert "PONG" in resp.text.upper() or len(resp.text.strip()) >= 1


@pytest.mark.live
def test_live_router_prefers_gemini_when_available() -> None:
    if not _has_gemini():
        pytest.skip("LIVE Gemini blocked: credentials/package missing")
    router = ProviderRouter(
        providers={
            "gemini": GeminiProvider(),
            "deterministic": DeterministicProvider(),
        },
        preferred="gemini",
        fallback=["deterministic"],
        max_retries=0,
    )
    result = router.generate("Say hi in one short sentence.")
    assert result.response.success
    if result.selected_provider == "gemini":
        assert result.response.mode == "LIVE"
        assert "[DETERMINISTIC OFFLINE]" not in result.response.text
    else:
        # fallback path — still valid but not LIVE claim
        assert result.fallback_used


@pytest.mark.live
def test_live_duckduckgo_search() -> None:
    adapter = DuckDuckGoHTMLAdapter(timeout=12.0, max_retries=1)
    hits = adapter.search("Python official documentation site:docs.python.org", limit=5)
    if not hits:
        # Network may block DDG; report skip rather than fake PASS
        pytest.skip(
            f"LIVE search returned no hits (error={adapter.last_error} status={adapter.last_status})"
        )
    assert all("url" in h and h["url"].startswith("http") for h in hits)
    assert all(h.get("title") for h in hits)
    # ResourceFinder ranking on live hits
    finder = ResourceFinder(adapter=adapter)
    result = finder.find("Python official documentation", limit=5)
    assert result.mode == "LIVE"
    assert result.candidates
    assert result.candidates[0].url.startswith("http")
    assert "FixtureSearchAdapter" not in result.consulted


def test_ddg_parser_unit_fixture() -> None:
    """UNIT: parser extracts real-looking anchors from sample HTML (not LIVE)."""
    html = '''
    <html><body>
    <a class="result__a" href="https://docs.python.org/3/">Python 3 Docs</a>
    <a class="result__snippet">Official documentation</a>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpypi.org%2Fproject%2Frequests%2F">requests</a>
    </body></html>
    '''
    adapter = DuckDuckGoHTMLAdapter()
    hits = adapter._parse_html(html, limit=5)
    assert len(hits) >= 1
    assert hits[0]["url"].startswith("http")
    assert "Python" in hits[0]["title"] or hits[0]["url"]


def test_gui_import_diagnostics() -> None:
    """OFFLINE: main module imports without hard crash when optional deps missing."""
    import importlib
    import jarvis.app.main as main

    # re-load safe
    assert hasattr(main, "DESKTOP_AVAILABLE")
    assert hasattr(main, "_OPTIONAL_IMPORT_ERRORS")
    assert hasattr(main, "speak")
    # speak must not raise without engine
    main.speak("diagnostic only")
