"""Connection-time destination check. Unit-level defense only."""

from __future__ import annotations

import ipaddress


def is_private_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def allow_connect(host: str, resolved_ip: str, prior_ip: str | None = None) -> dict:
    if is_private_ip(resolved_ip):
        return {"ok": False, "status": "BLOCKED", "reason": "private address"}
    if prior_ip and prior_ip != resolved_ip:
        return {"ok": False, "status": "BLOCKED", "reason": "ip changed before connect"}
    return {"ok": True, "status": "ALLOWED", "real_world_verified": False}
