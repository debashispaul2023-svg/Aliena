"""Phase C: multi-source search provider tests (MOCKED + optional LIVE)."""

from __future__ import annotations

import json
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
import requests

from jarvis.ai.providers.github import GitHubSearchAdapter
from jarvis.ai.providers.pypi import PyPISearchAdapter
from jarvis.ai.providers.multi import MultiSearchAdapter
from jarvis.ai.providers.web_search import DuckDuckGoHTMLAdapter
from jarvis.ai.resource_finder import ResourceFinder, FixtureSearchAdapter


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        text: str = "",
        headers: Optional[dict] = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


# -------------------------- GitHub unit tests --------------------------

def test_github_parse_success() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(
        200,
        {
            "items": [
                {
                    "full_name": "psf/requests",
                    "html_url": "https://github.com/psf/requests",
                    "description": "HTTP for Humans",
                    "stargazers_count": 50000,
                    "language": "Python",
                    "default_branch": "main",
                    "license": {"spdx_id": "Apache-2.0"},
                    "updated_at": "2024-01-01T00:00:00Z",
                },
                {"full_name": "", "html_url": ""},  # skipped
            ]
        },
    )
    adapter = GitHubSearchAdapter(session=session, max_retries=0)
    hits = adapter.search("requests", limit=5)
    assert len(hits) == 1
    assert hits[0]["source"] == "github"
    assert hits[0]["kind"] == "repo"
    assert hits[0]["url"].startswith("https://github.com/")
    assert hits[0]["license"] == "Apache-2.0"
    assert hits[0]["version"] == "main"


def test_github_empty_and_malformed() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(200, {"items": []})
    adapter = GitHubSearchAdapter(session=session)
    assert adapter.search("zzz") == []

    session.get.return_value = FakeResponse(200, payload=ValueError("bad json"))
    assert adapter.search("x") == []
    assert "Malformed" in (adapter.last_error or "")


def test_github_http_errors() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(401, {})
    adapter = GitHubSearchAdapter(session=session, max_retries=0)
    assert adapter.search("x") == []
    assert "Authentication" in (adapter.last_error or "")

    session.get.return_value = FakeResponse(429, {})
    adapter = GitHubSearchAdapter(session=session, max_retries=0)
    assert adapter.search("x") == []
    assert "Rate limit" in (adapter.last_error or "")


def test_github_timeout_retry() -> None:
    session = MagicMock()
    session.get.side_effect = [
        requests.Timeout("t"),
        FakeResponse(200, {"items": []}),
    ]
    adapter = GitHubSearchAdapter(session=session, max_retries=1)
    assert adapter.search("x") == []


def test_github_no_token_in_error_messages() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(403, {"message": "bad credentials secret-token-xyz"})
    adapter = GitHubSearchAdapter(session=session, token="ghp_SECRET_TOKEN_VALUE", max_retries=0)
    adapter.search("x")
    assert "ghp_SECRET" not in (adapter.last_error or "")


# -------------------------- PyPI unit tests --------------------------

def test_pypi_exact_project() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(
        200,
        {
            "info": {
                "name": "requests",
                "version": "2.32.0",
                "summary": "Python HTTP for Humans.",
                "project_url": "https://pypi.org/project/requests/",
                "requires_python": ">=3.8",
                "license": "Apache 2.0",
            }
        },
    )
    adapter = PyPISearchAdapter(session=session, max_retries=0)
    hits = adapter.search("requests", limit=3)
    assert hits
    assert hits[0]["source"] == "pypi"
    assert hits[0]["kind"] == "package"
    assert hits[0]["version"] == "2.32.0"
    assert hits[0]["url"].startswith("https://pypi.org/")


def test_pypi_404_empty() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(404, {})
    adapter = PyPISearchAdapter(session=session, max_retries=0)
    # HTML search also mocked empty
    assert adapter.search("this-package-does-not-exist-xyzzy") == []


def test_pypi_malformed_json() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(200, payload=ValueError("nope"))
    adapter = PyPISearchAdapter(session=session, max_retries=0)
    assert adapter.search("requests") == []
    assert "Malformed" in (adapter.last_error or "")


def test_pypi_rate_limit() -> None:
    session = MagicMock()
    session.get.return_value = FakeResponse(429, {})
    adapter = PyPISearchAdapter(session=session, max_retries=0)
    assert adapter.search("requests") == []
    assert "Rate limit" in (adapter.last_error or "")


def test_pypi_html_search_parse() -> None:
    session = MagicMock()
    # first call exact JSON 404, second HTML search
    html = '''
    <a href="https://pypi.org/project/httpx/">httpx</a>
    <a href="https://pypi.org/project/requests/">requests</a>
    '''
    session.get.side_effect = [
        FakeResponse(404, {}),
        FakeResponse(200, text=html),
    ]
    adapter = PyPISearchAdapter(session=session, max_retries=0)
    hits = adapter.search("http client", limit=5)
    assert any(h["title"] == "httpx" for h in hits)
    assert all(h["source"] == "pypi" for h in hits)
    # version unknown from HTML — must remain None/absent, not invented
    for h in hits:
        assert h.get("version") in (None, "")


# -------------------------- Multi + finder --------------------------

def test_multi_dedup_and_attribution() -> None:
    class A:
        mode = "MOCKED"
        last_error = None

        def search(self, query, limit=5):
            return [
                {"title": "Same", "url": "https://example.com/a", "source": "a", "kind": "docs"},
                {"title": "OnlyA", "url": "https://example.com/only-a", "source": "a", "kind": "docs"},
            ]

    class B:
        mode = "MOCKED"
        last_error = None

        def search(self, query, limit=5):
            return [
                {"title": "Same", "url": "https://example.com/a", "source": "b", "kind": "docs"},
                {"title": "OnlyB", "url": "https://example.com/only-b", "source": "b", "kind": "package"},
            ]

    multi = MultiSearchAdapter([A(), B()])
    hits = multi.search("x", limit=5)
    urls = [h["url"] for h in hits]
    assert urls.count("https://example.com/a") == 1
    assert "https://example.com/only-b" in urls


def test_finder_ranks_github_and_pypi() -> None:
    fixtures = {
        "requests": [
            {
                "title": "random blog",
                "url": "http://example.com/blog",
                "source": "blog",
                "kind": "other",
            },
            {
                "title": "psf/requests",
                "url": "https://github.com/psf/requests",
                "source": "github",
                "kind": "repo",
                "stars": 50000,
            },
            {
                "title": "requests",
                "url": "https://pypi.org/project/requests/",
                "source": "pypi",
                "kind": "package",
                "version": "2.32.0",
            },
        ]
    }
    finder = ResourceFinder(adapter=FixtureSearchAdapter(fixtures))
    result = finder.find("requests")
    assert result.mode == "MOCKED"
    assert result.candidates
    # pypi/github should outrank random blog
    assert result.candidates[0].source in {"pypi", "github"}


def test_missing_metadata_not_invented() -> None:
    adapter = GitHubSearchAdapter(session=MagicMock())
    adapter._session.get.return_value = FakeResponse(
        200,
        {
            "items": [
                {
                    "full_name": "org/pkg",
                    "html_url": "https://github.com/org/pkg",
                    "description": None,
                    "license": None,
                }
            ]
        },
    )
    hits = adapter.search("pkg")
    assert hits[0]["description"] == ""
    assert hits[0]["license"] is None


@pytest.mark.live
def test_live_github_search() -> None:
    adapter = GitHubSearchAdapter(timeout=12.0, max_retries=1)
    hits = adapter.search("requests language:Python", limit=3)
    if not hits:
        pytest.skip(f"LIVE GitHub blocked/empty: {adapter.last_error} status={adapter.last_status}")
    assert all(h.get("source") == "github" for h in hits)
    assert all(str(h.get("url", "")).startswith("https://github.com/") for h in hits)


@pytest.mark.live
def test_live_pypi_search() -> None:
    adapter = PyPISearchAdapter(timeout=12.0, max_retries=1)
    hits = adapter.search("requests", limit=3)
    if not hits:
        pytest.skip(f"LIVE PyPI blocked/empty: {adapter.last_error} status={adapter.last_status}")
    assert any(h.get("source") == "pypi" for h in hits)
    assert any("pypi.org" in str(h.get("url", "")) for h in hits)


@pytest.mark.live
def test_live_multi_finder() -> None:
    multi = MultiSearchAdapter(
        [PyPISearchAdapter(timeout=12.0), GitHubSearchAdapter(timeout=12.0)]
    )
    finder = ResourceFinder(adapter=multi)
    result = finder.find("requests", limit=5)
    if not result.candidates:
        pytest.skip(f"LIVE multi empty: errors={getattr(multi, 'last_errors', {})}")
    assert result.mode == "LIVE"
    sources = {c.source for c in result.candidates}
    assert sources & {"pypi", "github"}
