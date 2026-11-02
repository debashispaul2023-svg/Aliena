"""Optional ElevenLabs TTS. Falls back if key or network is missing.

Does not store the API key. Reads ELEVENLABS_API_KEY or XI_API_KEY.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests

DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel — natural default
DEFAULT_MODEL = "eleven_multilingual_v2"
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def api_key() -> Optional[str]:
    return os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("XI_API_KEY")


def synthesize(
    text: str,
    *,
    voice_id: Optional[str] = None,
    model_id: str = DEFAULT_MODEL,
    out_path: Optional[Path] = None,
) -> Optional[Path]:
    """Return path to an mp3, or None if unavailable."""
    key = api_key()
    if not key or not text or not text.strip():
        return None
    vid = voice_id or DEFAULT_VOICE_ID
    try:
        resp = requests.post(
            API_URL.format(voice_id=vid),
            headers={
                "xi-api-key": key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json={
                "text": text[:2500],
                "model_id": model_id,
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        target = out_path or Path("/tmp/jarvis_tts.mp3")
        target.write_bytes(resp.content)
        return target
    except Exception:
        return None
