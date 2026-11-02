"""Free neural TTS via Microsoft Edge voices. No API key.

Not an ElevenLabs clone. Similar natural style, no account needed.
Requires network to Microsoft's public TTS endpoint.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

# Natural default: en-US-JennyNeural (calm, clear).
DEFAULT_VOICE = "en-US-JennyNeural"
# Closer to a male assistant: en-US-GuyNeural, en-GB-RyanNeural


async def _save(text: str, voice: str, path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text[:2500], voice)
    await communicate.save(str(path))


def synthesize(
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    out_path: Optional[Path] = None,
) -> Optional[Path]:
    if not text or not text.strip():
        return None
    target = out_path or Path("/tmp/jarvis_edge_tts.mp3")
    try:
        asyncio.run(_save(text, voice, target))
        return target if target.exists() and target.stat().st_size > 0 else None
    except Exception:
        return None
