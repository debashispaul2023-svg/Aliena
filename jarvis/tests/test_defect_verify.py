"""Defect verification: delegation timeout and SSRF."""

from __future__ import annotations

import time

import pytest

from jarvis.adapt.delegation import delegate
from jarvis.integrations.agent_reach.security import SecurityError, validate_url


def test_caller_timeout_does_not_wait_for_worker():
    def slow():
        time.sleep(0.25)
        return {"done": True}

    started = time.perf_counter()
    out = delegate([("slow", slow)], timeout=0.03)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.1
    assert any(item.get("error") == "caller_timeout" for item in out)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://localhost/",
    ],
)
def test_ssrf_blocked(url):
    with pytest.raises(SecurityError):
        validate_url(url)


def test_reserved_and_mapped_blocked():
    for url in ("http://240.0.0.1/", "http://[::ffff:10.0.0.1]/"):
        with pytest.raises(SecurityError):
            validate_url(url)


def test_repeated_timeouts_do_not_block():
    def slow():
        time.sleep(0.2)
        return {"done": True}
    for _ in range(3):
        started = time.perf_counter()
        out = delegate([("slow", slow)], timeout=0.03)
        assert time.perf_counter() - started < 0.1
        assert any(item.get("error") == "caller_timeout" for item in out)
        # Running thread is not reported as terminated.
        assert any(item.get("cancelled") is False for item in out)
