"""Feature 7 final verification. Mocked providers only."""

from __future__ import annotations

import threading

import pytest

from jarvis.voice.session import MockSTT, MockTTS, VoicePipeline


class SlowSTT(MockSTT):
    def transcribe(self, audio: bytes, language: str = "en") -> str:
        import time
        time.sleep(0.4)
        return super().transcribe(audio, language)


def test_cancel_during_stt():
    pipe = VoicePipeline(SlowSTT(), MockTTS())

    def cancel_soon():
        import time
        time.sleep(0.1)
        pipe.cancel()

    threading.Thread(target=cancel_soon, daemon=True).start()
    with pytest.raises(RuntimeError):
        pipe.handle_audio(b"audio")
    assert pipe.session.state in {"IDLE", "ERROR", "INTERRUPTED"}


def test_repeated_sessions():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    first = pipe.handle_audio(b"a", language="en")
    second = pipe.handle_audio(b"a", language="bn")
    assert b"hello" in first
    assert b"nomoshkar" in second
    assert pipe.session.state == "IDLE"


def test_malformed_audio_recovers():
    pipe = VoicePipeline(MockSTT(), MockTTS())
    with pytest.raises(RuntimeError):
        pipe.handle_audio(b"")
    pipe.recover()
    assert pipe.session.state == "IDLE"
    assert b"hello" in pipe.handle_audio(b"ok")
