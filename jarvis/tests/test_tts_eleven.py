"""ElevenLabs TTS unit tests. No network call without a key."""

from jarvis.app.tts_eleven import api_key, synthesize


def test_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("XI_API_KEY", raising=False)
    assert api_key() is None
    assert synthesize("hello") is None
