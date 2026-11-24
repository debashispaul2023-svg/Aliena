"""Keyboard interaction tests. No microphone required."""

from pathlib import Path

from jarvis.keyboard.controller import CommandHistory, CommandParser, CommandRouter, InteractionModeManager


def test_empty_input():
    assert CommandParser().parse("")["status"] == "EMPTY"


def test_help_and_clear():
    assert CommandRouter().route(CommandParser().parse("help"))["status"] == "HELP"
    assert CommandRouter().route(CommandParser().parse("clear"))["status"] == "CLEAR"


def test_history_and_privacy(tmp_path: Path):
    path = tmp_path / "history.txt"
    hist = CommandHistory(path)
    hist.add("open project")
    hist.add("token=secret")
    reloaded = CommandHistory(path)
    assert "open project" in reloaded.items
    assert all("token" not in item.lower() for item in reloaded.items)


def test_generated_execution_blocked():
    result = CommandRouter().route(CommandParser().parse("run generated server"))
    assert result["status"] == "BLOCKED"


def test_keyboard_mode_without_mic():
    assert InteractionModeManager().current(mic_available=False) == "keyboard"
