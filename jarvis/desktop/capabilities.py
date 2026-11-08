"""Desktop capability registry. Fail closed when hardware is unavailable."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field


@dataclass
class CapabilityReport:
    platform: str
    is_desktop: bool
    is_termux: bool
    capabilities: dict[str, str] = field(default_factory=dict)
    status: str = "UNSUPPORTED"


def _is_termux() -> bool:
    return (
        "ANDROID_ROOT" in os.environ
        or "/data/data/com.termux" in os.environ.get("PREFIX", "")
        or "TERMUX_VERSION" in os.environ
    )


def detect_environment() -> CapabilityReport:
    system = platform.system()
    termux = _is_termux()
    is_desktop = system in {"Windows", "Darwin", "Linux"} and not termux
    caps = {
        "mouse": "UNVERIFIED" if is_desktop else "BLOCKED",
        "keyboard": "UNVERIFIED" if is_desktop else "BLOCKED",
        "window": "UNVERIFIED" if is_desktop else "BLOCKED",
        "screenshot": "UNVERIFIED" if is_desktop else "BLOCKED",
        "app_launch": "UNVERIFIED" if is_desktop else "BLOCKED",
        "browser": "UNVERIFIED" if is_desktop else "BLOCKED",
        "file_explorer": "UNVERIFIED" if is_desktop else "BLOCKED",
    }
    status = "PARTIAL" if is_desktop else "UNSUPPORTED"
    return CapabilityReport(
        platform=system,
        is_desktop=is_desktop,
        is_termux=termux,
        capabilities=caps,
        status=status,
    )
