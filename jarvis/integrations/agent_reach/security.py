"""URL and secret safety for Agent Reach calls.

Fail closed on private, loopback, link-local, and unspecified addresses.
DNS that resolves to a prohibited address is rejected. Redirects are not followed.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
SECRET_RE = re.compile(r"(api[_-]?key|token|cookie|password|secret)\s*[:=]\s*\S+", re.I)


class SecurityError(ValueError):
    """Unsafe URL or command."""


def _blocked_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SecurityError("only http(s) URLs are allowed")
    host = (parsed.hostname or "").lower().strip("[]")
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        raise SecurityError("unsafe host")
    if _blocked_ip(host):
        raise SecurityError("prohibited address")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SecurityError(f"dns failed: {exc}") from exc
    for info in infos:
        addr = info[4][0]
        if _blocked_ip(addr):
            raise SecurityError(f"dns resolves to prohibited address: {addr}")
    return url


def redact(text: str) -> str:
    return SECRET_RE.sub(r"\1=[REDACTED]", text or "")
