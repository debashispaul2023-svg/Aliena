"""Targeted checks for safe Feature 4-7 additions."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.dev.drafts import apply_approved_draft, approve_code_draft, create_code_draft
from jarvis.dev.workspace import DevWorkspace
from jarvis.voice.session import MockSTT, MockTTS, VoicePipeline


def test_protected_env_blocked(tmp_path: Path):
    ws = DevWorkspace(tmp_path, "demo")
    change = type("C", (), {"path": ".env", "content": "KEY=1\n"})()
    draft = create_code_draft(ws, [change], project_id="demo")
    approve_code_draft(draft, reviewer="reviewer", fingerprint=draft.fingerprint)
    with pytest.raises(Exception):
        apply_approved_draft(ws, draft)


def test_voice_device_status_blocked():
    pipe = VoicePipeline(MockSTT(), MockTTS(), microphone_available=False)
    assert pipe.device_status()["microphone"] == "BLOCKED"
