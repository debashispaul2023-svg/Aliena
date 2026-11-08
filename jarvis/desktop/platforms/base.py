"""Platform adapter interface. Real adapters must never pretend success without evidence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PlatformAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
