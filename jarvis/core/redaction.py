"""Shared secret redaction (additive).

Superset of the three pre-existing, slightly different redactors
(``dev.test_runner.redact``, ``skills.runner.redact_text``,
``integrations.agent_reach.security.redact``). Those are left untouched.

Design rules:
* Pure functions, standard library only, never raises.
* Never returns or logs the secret it removed.
* Redaction replaces the *value*, keeping the key so logs stay readable.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_KEY_NAMES = (
    r"api[_\s-]?key|apikey|secret|client[_\s-]?secret|password|passwd|pwd|"
    r"token|access[_\s-]?token|auth[_\s-]?token|authorization|private[_\s-]?key"
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private key blocks (multi-line)
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
        REDACTED,
    ),
    # key = value / key: value / "key": "value"  (value redacted, key kept)
    (
        re.compile(
            r"""(?ix)
            (\b(?:%s)\b["']?\s*[:=]\s*)       # key and separator
            (?:(?:bearer|basic)\s+)?          # optional auth scheme belongs to the value
            (?:"[^"]*"|'[^']*'|[^\s,;&"']+)   # value
            """
            % _KEY_NAMES
        ),
        r"\1" + REDACTED,
    ),
    # Authorization: Bearer xxxx / Bearer xxxx
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 " + REDACTED),
    # credentials embedded in URLs  scheme://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1" + REDACTED + "@"),
    # well-known token shapes
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), REDACTED),
    (re.compile(r"\bxai-[A-Za-z0-9_\-]{20,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}"), REDACTED),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), REDACTED),
]


def redact_secrets(text: Any) -> str:
    """Return ``text`` (coerced to ``str``) with secret-looking substrings replaced.

    Never raises: on any internal error the safest output (a fixed marker) is
    returned rather than the unredacted input.
    """
    try:
        if text is None:
            return ""
        out = text if isinstance(text, str) else str(text)
        for pattern, repl in _PATTERNS:
            out = pattern.sub(repl, out)
        return out
    except Exception:  # pragma: no cover - defensive, fail closed
        return REDACTED


def redact_value(value: Any) -> Any:
    """Recursively redact strings inside lists, tuples and dicts."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {k: (REDACTED if _KEY_ONLY.search(str(k)) and not isinstance(v, (dict, list, tuple)) else redact_value(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(v) for v in value)
    return value


_KEY_ONLY = re.compile(r"(?i)^(%s)$" % _KEY_NAMES)

__all__ = ["REDACTED", "redact_secrets", "redact_value"]
