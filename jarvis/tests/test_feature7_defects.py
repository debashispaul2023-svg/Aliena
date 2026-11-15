"""Feature 7 defect regression tests. Mocked providers only."""

from __future__ import annotations

import pytest

from jarvis.voice.session import MockSTT, MockTTS, VoicePipeline


class FailSTT(MockSTT):
    def transcribe(self, audio: bytes, language: str = "en") -> str:
        raise RuntimeError("stt down")


def test_empty_audio_goes_to_error():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    with pytest.raises(RuntimeError):
        pipe.handle_audio(b"")
    assert pipe.session.state == "ERROR"
    pipe.recover()
    assert pipe.session.state == "IDLE"


def test_stt_failure_is_recoverable():
    pipe = VoicePipeline(FailSTT(), MockTTS())
    with pytest.raises(RuntimeError):
        pipe.handle_audio(b"audio")
    assert pipe.session.state == "ERROR"
    pipe.recover()
    assert pipe.session.state == "IDLE"


def test_bengali_and_english_mock():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    assert b"hello" in pipe.handle_audio(b"a", language="en")
    assert b"nomoshkar" in pipe.handle_audio(b"a", language="bn")


def test_busy_pipeline_rejected():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    pipe.session.transition("LISTENING")
    with pytest.raises(RuntimeError):
        pipe.handle_audio(b"a")
