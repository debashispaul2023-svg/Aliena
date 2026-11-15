"""Feature 7 voice interfaces and state machine. No background recording."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol

STATES = {"IDLE", "LISTENING", "PROCESSING", "THINKING", "SPEAKING", "INTERRUPTED", "ERROR"}
ALLOWED = {
    "IDLE": {"LISTENING", "ERROR"},
    "LISTENING": {"PROCESSING", "IDLE", "ERROR", "INTERRUPTED"},
    "PROCESSING": {"THINKING", "SPEAKING", "ERROR", "INTERRUPTED"},
    "THINKING": {"SPEAKING", "ERROR", "INTERRUPTED"},
    "SPEAKING": {"IDLE", "INTERRUPTED", "ERROR"},
    "INTERRUPTED": {"IDLE", "LISTENING"},
    "ERROR": {"IDLE"},
}


class SpeechRecognitionProvider(Protocol):
    def transcribe(self, audio: bytes, language: str = "en") -> str: ...


class TextToSpeechProvider(Protocol):
    def synthesize(self, text: str, voice: str = "male-indian") -> bytes: ...


@dataclass
class VoiceSession:
    state: str = "IDLE"
    transcript: str = ""
    reply: str = ""
    history: list[str] = field(default_factory=list)

    def transition(self, new_state: str) -> None:
        if new_state not in STATES or new_state not in ALLOWED.get(self.state, set()):
            raise ValueError(f"invalid transition {self.state} -> {new_state}")
        self.state = new_state
        self.history.append(new_state)


class MockSTT:
    def transcribe(self, audio: bytes, language: str = "en") -> str:
        if not audio:
            raise ValueError("empty audio")
        return "hello" if language == "en" else "nomoshkar"


class MockTTS:
    def synthesize(self, text: str, voice: str = "male-indian") -> bytes:
        if not text.strip():
            raise ValueError("empty text")
        return f"{voice}:{text}".encode("utf-8")


@dataclass
class VoiceSettings:
    language: str = "en"
    voice: str = "male-indian"
    rate: float = 1.0

    def validate(self) -> None:
        if self.language not in {"en", "bn"}:
            raise ValueError("unsupported language")
        if not 0.5 <= self.rate <= 2.0:
            raise ValueError("rate out of range")


class VoicePipeline:
    def __init__(
        self,
        stt: SpeechRecognitionProvider,
        tts: TextToSpeechProvider,
        timeout_s: float = 5.0,
        settings: VoiceSettings | None = None,
        microphone_available: bool = False,
    ) -> None:
        self.stt = stt
        self.tts = tts
        self.timeout_s = timeout_s
        self.settings = settings or VoiceSettings()
        self.settings.validate()
        self.microphone_available = microphone_available
        self.session = VoiceSession()
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    def device_status(self) -> dict:
        return {
            "microphone": "available" if self.microphone_available else "BLOCKED",
            "playback": "UNVERIFIED",
        }

    def handle_audio(self, audio: bytes, language: str = "en") -> bytes:
        with self._lock:
            if self.session.state != "IDLE":
                raise RuntimeError(f"pipeline busy in {self.session.state}")
            self._cancel.clear()
            self.session.transition("LISTENING")
        try:
            if self._cancel.is_set():
                raise RuntimeError("cancelled")
            if not audio:
                raise ValueError("empty audio")
            with self._lock:
                self.session.transition("PROCESSING")
            self.session.transcript = self.stt.transcribe(audio, language)
            if self._cancel.is_set():
                raise RuntimeError("cancelled")
            with self._lock:
                self.session.transition("THINKING")
            self.session.reply = f"Heard: {self.session.transcript}"
            with self._lock:
                self.session.transition("SPEAKING")
            audio_out = self.tts.synthesize(self.session.reply)
            if self._cancel.is_set():
                raise RuntimeError("cancelled")
            with self._lock:
                self.session.transition("IDLE")
            return audio_out
        except Exception as exc:
            with self._lock:
                if self.session.state not in {"ERROR", "IDLE"}:
                    try:
                        self.session.transition("ERROR")
                    except ValueError:
                        self.session.state = "ERROR"
            raise RuntimeError(str(exc)) from exc

    def recover(self) -> None:
        with self._lock:
            if self.session.state == "ERROR":
                self.session.transition("IDLE")

    def cleanup(self) -> None:
        self._cancel.set()
        with self._lock:
            self.session.state = "IDLE"

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            if self.session.state not in {"IDLE", "ERROR"}:
                self.session.transition("INTERRUPTED")
                self.session.transition("IDLE")
