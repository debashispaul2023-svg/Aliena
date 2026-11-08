"""Least-privilege permission manager for desktop actions."""

from __future__ import annotations

from dataclasses import dataclass, field


ALLOWED_ACTIONS = {
    "detect_environment",
    "list_capabilities",
    "launch_app",
    "focus_window",
    "click",
    "type_text",
    "screenshot",
    "inspect_screen",
    "open_url",
    "open_path",
    "cancel",
}


@dataclass
class PermissionManager:
    granted: set[str] = field(default_factory=set)

    def grant(self, action: str) -> None:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unknown action: {action}")
        self.granted.add(action)

    def revoke(self, action: str) -> None:
        self.granted.discard(action)

    def has(self, action: str) -> bool:
        return action in self.granted

    def require(self, action: str) -> None:
        if action not in ALLOWED_ACTIONS:
            raise PermissionError(f"action not allowed: {action}")
        if action not in self.granted:
            raise PermissionError(f"permission denied: {action}")
