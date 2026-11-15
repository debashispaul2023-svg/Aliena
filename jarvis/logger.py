"""Centralized logging setup for Jarvis.

Extracted so every subsystem can share the same logger and the
log_and_print helper without duplicating basicConfig calls.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from jarvis.core.redaction import redact_secrets

_configured = False
logger = logging.getLogger("jarvis")


class RedactingFilter(logging.Filter):
    """Redact secret-looking text from a record's message, args and traceback.

    Never raises and never drops a record: if redaction itself fails the
    message is replaced by a fixed marker rather than passed through.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_secrets(record.getMessage())
            record.args = ()
            if record.exc_info and not record.exc_text:
                record.exc_text = redact_secrets(
                    logging.Formatter().formatException(record.exc_info)
                )
            elif record.exc_text:
                record.exc_text = redact_secrets(record.exc_text)
            if record.stack_info:
                record.stack_info = redact_secrets(record.stack_info)
        except Exception:
            record.msg = "[REDACTED]"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


class RedactingFormatter(logging.Formatter):
    """Second line of defence: redact the fully formatted output."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


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

    # Idempotent: remove any earlier RedactingFilter before adding one.
    for f in list(logger.filters):
        if isinstance(f, RedactingFilter):
            logger.removeFilter(f)
    logger.addFilter(RedactingFilter())

    formatter = RedactingFormatter("%(asctime)s | %(levelname)s | %(message)s")

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
    safe = redact_secrets(msg)
    print(safe)
    log_fn = getattr(logger, level, logger.info)
    try:
        log_fn(safe)
    except Exception:
        # Never let logging failures crash the assistant
        pass
