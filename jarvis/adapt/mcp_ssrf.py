"""SSRF checks for Fetch MCP. Blocks private and metadata targets."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def is_blocked_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "bad_scheme"
    host = (parsed.hostname or "").lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        return "blocked_host"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return "blocked_ip"
    except ValueError:
        pass
    if host == "169.254.169.254":
        return "metadata"
    return None
