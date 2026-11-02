"""Configuration management for Jarvis.

Extracted from the original monolithic script. Preserves the same
DEFAULT_CONFIG keys and load/save behavior, with an optional base_dir
so tests and different entry points can control where files live.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Exact copy of the original DEFAULT_CONFIG
DEFAULT_CONFIG: dict[str, Any] = {
    "assistant_name": "Jarvis",
    "user_name": "Sir",
    "wake_word": "jarvis",
    "wake_word_aliases": ["jarvis", "hey jarvis"],
    "personality_level": "high",  # "high" = খুব sassy, "low" = shonto/calm
    "voice_rate": 170,
    "voice_volume": 1.0,
    "voice_index": None,  # None হলে auto-detect female ভয়েস, নাহলে নির্দিষ্ট index ব্যবহার হবে
    "default_city": "",
    "max_memory_turns": 6,
    "speech_languages": ["bn-BD", "en-IN", "hi-IN"],
}


def _resolve_base_dir(base_dir: str | Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir).resolve()
    # Prefer an explicit env var, otherwise current working directory
    # (matches the original single-file behavior when run from its directory).
    env = os.environ.get("JARVIS_BASE_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd()


def config_path(base_dir: str | Path | None = None) -> Path:
    return _resolve_base_dir(base_dir) / "jarvis_config.json"


def load_config(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Load config, merging with defaults. Never raises on missing/corrupt file."""
    path = config_path(base_dir)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return dict(DEFAULT_CONFIG)
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            # Caller can log; we stay quiet here so this module has no logging dependency.
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config: dict[str, Any], base_dir: str | Path | None = None) -> None:
    """Persist config. Silently ignores write errors (original behavior)."""
    path = config_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass
