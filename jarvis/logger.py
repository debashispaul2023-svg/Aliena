"""Centralized logging setup for Jarvis.

Extracted so every subsystem can share the same logger and the
log_and_print helper without duplicating basicConfig calls.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_configured = False
logger = logging.getLogger("jarvis")


def setup_logging(
    log_file: Optional[str | Path] = None,
    level: int = logging.INFO,
    force: bool = False,
) -> logging.Logger:
    """Configure the 'jarvis' logger once.

    If log_file is None, logs go to stderr (useful for tests / headless).
    """
    global _configured
    if _configured and not force:
        return logger

    logger.setLevel(level)
    # Remove any existing handlers to avoid duplicates on re-init
    for h in list(logger.handlers):
        logger.removeHandler(h)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    # Always also emit to stderr so interactive runs stay visible
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    logger.propagate = False
    _configured = True
    return logger


def log_and_print(msg: str, level: str = "info") -> None:
    """Print to console and log at the given level (preserves original helper)."""
    print(msg)
    log_fn = getattr(logger, level, logger.info)
    try:
        log_fn(msg)
    except Exception:
        # Never let logging failures crash the assistant
        pass
