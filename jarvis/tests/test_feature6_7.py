"""Feature 6 and 7 tests. No live downloads or microphone use."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from jarvis.resources.safety import is_blocked_host, safe_extract_zip, validate_download_url
from jarvis.voice.session import VoicePipeline, MockSTT, MockTTS


def test_block_localhost_and_private():
    assert is_blocked_host("localhost")
    assert is_blocked_host("127.0.0.1")
    assert is_blocked_host("10.0.0.1")
    with pytest.raises(ValueError):
        validate_download_url("http://127.0.0.1/file")


def test_archive_path_escape(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "nope")
    with pytest.raises(ValueError):
        safe_extract_zip(archive, tmp_path / "out")


def test_voice_pipeline_and_cancel():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    out = pipe.handle_audio(b"audio", language="en")
    assert b"Heard: hello" in out
    assert pipe.session.state == "IDLE"
    pipe.session.transition("LISTENING")
    pipe.cancel()
    assert pipe.session.state == "IDLE"


def test_invalid_voice_transition():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    with pytest.raises(ValueError):
        pipe.session.transition("SPEAKING")
