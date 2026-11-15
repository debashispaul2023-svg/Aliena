"""Audio device probe. Missing hardware returns UNVERIFIED, not success."""

from __future__ import annotations


def probe_audio() -> dict:
    try:
        import sounddevice  # type: ignore
    except Exception:
        return {"available": False, "status": "UNVERIFIED", "reason": "sounddevice missing"}
    return {"available": True, "status": "UNVERIFIED", "reason": "library present, hardware not proven"}
