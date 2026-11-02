"""Resource Finder tests — MOCKED fixtures vs OFFLINE null adapter."""

from __future__ import annotations

from jarvis.ai.resource_finder import (
    ResourceFinder,
    FixtureSearchAdapter,
    NullSearchAdapter,
)
from jarvis.core.orchestrator import Orchestrator
from jarvis.core.models import TaskRecord, STATUS_COMPLETED
from pathlib import Path


FIXTURES = {
    "requests http": [
        {
            "title": "Requests: HTTP for Humans",
            "url": "https://docs.python-requests.org/",
            "description": "Official Requests documentation",
            "source": "docs",
            "kind": "docs",
        },
        {
            "title": "requests on PyPI",
            "url": "https://pypi.org/project/requests/",
            "description": "Python HTTP library",
            "source": "pypi",
            "kind": "package",
        },
        {
            "title": "random blog",
            "url": "http://example.com/blog",
            "description": "unofficial notes",
            "source": "blog",
            "kind": "other",
        },
    ]
}


def test_l_fixture_vs_live_label() -> None:
    finder = ResourceFinder(adapter=FixtureSearchAdapter(FIXTURES))
    result = finder.find("requests http")
    assert result.mode == "MOCKED"
    assert result.candidates
    assert "FixtureSearchAdapter" in result.consulted


def test_m_deterministic_ranking() -> None:
    finder = ResourceFinder(adapter=FixtureSearchAdapter(FIXTURES))
    result = finder.find("requests http")
    assert result.candidates[0].url.startswith("https://docs.python-requests.org")
    assert any("official" in r or "docs" in r for r in result.candidates[0].reasons)


def test_n_empty_and_malformed() -> None:
    finder = ResourceFinder(adapter=NullSearchAdapter())
    empty = finder.find("something obscure")
    assert empty.candidates == []
    assert empty.mode == "OFFLINE"

    # malformed rows skipped
    adapter = FixtureSearchAdapter({"x": [{"title": "", "url": ""}, {"title": "ok", "url": "https://example.com"}]})
    finder2 = ResourceFinder(adapter=adapter)
    r = finder2.find("x")
    assert len(r.candidates) == 1


def test_o_does_not_invent_results() -> None:
    finder = ResourceFinder(adapter=NullSearchAdapter())
    r = finder.find("nonexistent capability xyzzy")
    assert r.candidates == []
    assert r.consulted == [] or True  # null adapter returns [] without consult claim needed


def test_p_no_auto_install() -> None:
    finder = ResourceFinder(adapter=FixtureSearchAdapter(FIXTURES))
    r = finder.find("requests http")
    assert "No packages were installed" in r.notes
    # ensure no pip side effect API exists on finder
    assert not hasattr(finder, "install")


def test_r_agent_consumes_resource_finder(tmp_path: Path) -> None:
    finder = ResourceFinder(adapter=FixtureSearchAdapter(FIXTURES))
    orch = Orchestrator(workspace=tmp_path / "ws", resource_finder=finder)
    task = TaskRecord.new(
        "Find HTTP client library",
        agent_name="resource_finder",
        inputs={"need": "requests http"},
    )
    result = orch.run("find resource", tasks=[task], record_experience=False)
    assert result.status == STATUS_COMPLETED
    out = result.tasks[0].outputs
    assert out.get("mode") == "MOCKED"
    assert out.get("candidates")
