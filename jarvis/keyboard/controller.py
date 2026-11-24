"""Keyboard-first command input. Works without a microphone."""

from __future__ import annotations

from collections import deque
from pathlib import Path


class CommandHistory:
    def __init__(self, path: Path | None = None, limit: int = 50) -> None:
        self.path = path
        self.items: deque[str] = deque(maxlen=limit)
        if path and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line and "key" not in line.lower() and "token" not in line.lower():
                    self.items.append(line[:200])

    def add(self, command: str) -> None:
        text = command.strip()
        if not text:
            return
        self.items.append(text[:200])
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("\n".join(self.items), encoding="utf-8")

    def previous(self) -> str:
        return self.items[-1] if self.items else ""


class TextInputController:
    def submit(self, text: str) -> str:
        return text.strip()


class CommandParser:
    def parse(self, text: str) -> dict:
        cleaned = text.strip()
        if not cleaned:
            return {"ok": False, "status": "EMPTY"}
        if cleaned.lower() == "help":
            return {"ok": True, "status": "HELP", "command": cleaned}
        if cleaned.lower() in {"clear", "cls"}:
            return {"ok": True, "status": "CLEAR", "command": cleaned}
        if len(cleaned) > 2000:
            return {"ok": False, "status": "TOO_LONG"}
        return {"ok": True, "status": "COMMAND", "command": cleaned}


class CommandRouter:
    def route(self, parsed: dict) -> dict:
        if not parsed.get("ok"):
            return {"executed": False, "status": parsed.get("status", "INVALID")}
        if parsed["status"] == "HELP":
            return {"executed": False, "status": "HELP", "text": "Commands: help, clear, history"}
        if parsed["status"] == "CLEAR":
            return {"executed": False, "status": "CLEAR"}
        if "run generated" in parsed["command"].lower():
            return {"executed": False, "status": "BLOCKED", "phase6f": "BLOCKED"}
        return {"executed": False, "status": "QUEUED", "command": parsed["command"]}


class InteractionModeManager:
    def current(self, mic_available: bool = False) -> str:
        return "voice" if mic_available else "keyboard"
