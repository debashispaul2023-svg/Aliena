"""Path-aware sensitive file policy.

Rules are explicit. Ordinary names containing 'secret', 'token', or 'key'
are not blocked. Symlink checks are time-of-check only; race protection is not claimed.
"""

from __future__ import annotations

import re
from pathlib import Path

ENV_EXACT = {
    ".env",
    ".env.bak",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    ".env.example",
}
PRIVATE_KEYS = {
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
}
CREDENTIAL_FILES = {
    "credentials.json",
    "service-account.json",
    "secrets.json",
    "token.json",
    ".netrc",
    ".pgpass",
    "kubeconfig",
    "credentials",
}
SENSITIVE_SUFFIXES = {".pem", ".p12", ".pfx"}
ENV_VARIANT = re.compile(r"^\.env(\..+)?$", re.IGNORECASE)


def _windows_canonical(name: str) -> str:
    """Name as Windows would resolve it: NTFS alternate-data-stream suffix
    (``file:stream``) removed, then trailing dots and spaces stripped.

    ``.env.``, ``.env `` and ``.env::$DATA`` all open the real ``.env`` on Windows,
    so they must be judged by their canonical form (verified bypass, Phase 5).
    """
    base = name.split(":", 1)[0]
    return base.rstrip(" .")


def _is_sensitive_exact(name: str) -> bool:
    low = name.lower()
    if low.endswith(".pub"):
        return False
    if low in {n.lower() for n in ENV_EXACT | PRIVATE_KEYS | CREDENTIAL_FILES}:
        return True
    if ENV_VARIANT.match(name):
        return True
    if any(low.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
        return True
    return False


def is_sensitive_name(name: str) -> bool:
    if _is_sensitive_exact(name):
        return True
    canonical = _windows_canonical(name)
    return bool(canonical) and canonical != name and _is_sensitive_exact(canonical)


def is_sensitive_relative(raw_path: str) -> bool:
    normalized = raw_path.replace("\\", "/").strip("/")
    parts = [p for p in normalized.split("/") if p not in {"", "."}]
    if not parts:
        return False
    last = _windows_canonical(parts[-1]).lower()
    if last == "config" and len(parts) >= 2 and _windows_canonical(parts[-2]).lower() == ".kube":
        return True
    return is_sensitive_name(parts[-1])


def assert_safe_workspace_path(workspace_root: Path, raw_path: str) -> Path:
    """Resolve inside workspace and reject known sensitive targets. Fail closed."""
    if not raw_path or not isinstance(raw_path, str):
        raise ValueError("empty path")
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("absolute path rejected")
    candidate = (workspace_root / normalized).resolve()
    root = workspace_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes workspace") from exc
    if candidate.is_symlink():
        raise ValueError("symlink rejected")
    if is_sensitive_relative(normalized):
        raise ValueError("protected path")
    return candidate
