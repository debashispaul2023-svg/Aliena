"""Validate desktop actions before any execution attempt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.desktop.permissions import ALLOWED_ACTIONS


@dataclass
class ActionRequest:
    action: str
    params: dict[str, Any]
    approved: bool = False


class ActionValidator:
    def validate(self, request: ActionRequest) -> None:
        if request.action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported action: {request.action}")
        if not isinstance(request.params, dict):
            raise ValueError("params must be a dict")
        if request.action == "type_text":
            text = request.params.get("text", "")
            if not isinstance(text, str) or len(text) > 2000:
                raise ValueError("type_text text invalid or too long")
        if request.action == "open_url":
            url = str(request.params.get("url", ""))
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError("open_url requires http(s) URL")
        if request.action == "open_path":
            path = str(request.params.get("path", ""))
            if ".." in path or path.startswith("/") and ".." in path:
                # path traversal rejection for automation params
                if ".." in path.replace("\\", "/").split("/"):
                    raise ValueError("path traversal rejected")
        if request.action in {"click", "focus_window", "launch_app", "screenshot", "open_url", "open_path", "type_text"}:
            if not request.approved:
                raise PermissionError("approval required")
