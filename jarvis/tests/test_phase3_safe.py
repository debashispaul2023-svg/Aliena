"""Focused safe checks for Features 4-7. No live provider or microphone use."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.voice.session import MockSTT, MockTTS, VoicePipeline, VoiceSettings


def test_voice_settings_reject_bad_language():
    with pytest.raises(ValueError):
        VoicePipeline(MockSTT(), MockTTS(), settings=VoiceSettings(language="xx"))


def test_voice_settings_accept_bengali():
    pipe = VoicePipeline(MockSTT(), MockTTS(), settings=VoiceSettings(language="bn"))
    assert pipe.device_status()["microphone"] == "BLOCKED"
    assert b"nomoshkar" in pipe.handle_audio(b"a", language="bn")


def test_phase6_still_blocked():
    text = Path("jarvis/dev/phase6_status.json").read_text()
    assert '"execution": "BLOCKED"' in text
