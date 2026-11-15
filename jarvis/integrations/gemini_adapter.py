"""Gemini adapter skeleton. Live verification requires a real key and a successful call."""

from __future__ import annotations

import os


class GeminiAdapter:
    def __init__(self) -> None:
        self.key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def status(self) -> dict:
        if not self.key:
            return {"configured": False, "verified": False, "status": "UNVERIFIED"}
        return {"configured": True, "verified": False, "status": "UNVERIFIED"}
