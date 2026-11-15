"""Additional Part B coverage for queue, voice cleanup, plugins, and freelancer status."""

from __future__ import annotations

import pytest

from jarvis.freelancer.status import external_action_status
from jarvis.plugins.registry import PluginManifest, PluginRegistry
from jarvis.resources.queue import DownloadQueue
from jarvis.voice.session import MockSTT, MockTTS, VoicePipeline


def test_download_queue_requires_https():
    q = DownloadQueue()
    with pytest.raises(ValueError):
        q.enqueue("http://example.com/a")
    job = q.enqueue("https://example.com/a")
    q.mark(job, "done")
    assert q.summary()["done"] == 1


def test_voice_cleanup_returns_idle():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    pipe.cleanup()
    assert pipe.session.state == "IDLE"


def test_plugin_rejects_shell_capability():
    reg = PluginRegistry()
    with pytest.raises(ValueError):
        reg.register(PluginManifest(name="bad", capabilities=["shell"]))


def test_freelancer_external_not_submitted():
    result = external_action_status("submit_proposal", confirmed=False)
    assert result["submitted"] is False
    assert result["status"] == "APPROVAL_REQUIRED"
