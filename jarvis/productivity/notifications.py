"""Notification queue. Delivery is not claimed unless a real provider confirms it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


State = Literal["created", "queued", "delivered", "failed", "unverified"]


@dataclass
class Notification:
    channel: str
    message: str
    state: State = "created"


class NotificationService:
    def __init__(self) -> None:
        self.items: list[Notification] = []

    def create(self, channel: str, message: str) -> Notification:
        if not message.strip():
            raise ValueError("message required")
        note = Notification(channel=channel, message=message[:200], state="queued")
        self.items.append(note)
        return note

    def mark_delivered(self, note: Notification, *, provider_confirmed: bool) -> None:
        note.state = "delivered" if provider_confirmed else "unverified"
