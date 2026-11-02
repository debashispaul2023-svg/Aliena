"""Detect the agent-reach CLI without requiring it at import time."""

from __future__ import annotations

import shutil
from typing import Optional


def find_cli() -> Optional[str]:
    return shutil.which("agent-reach")


def is_installed() -> bool:
    return find_cli() is not None
