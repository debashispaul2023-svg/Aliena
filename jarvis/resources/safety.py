"""Feature 6 safety helpers. Downloaded content is never executed."""

from __future__ import annotations

import ipaddress
import zipfile
from pathlib import Path
from urllib.parse import urlparse


def is_blocked_host(host: str) -> bool:
    low = (host or "").lower().strip(".")
    if low in {"localhost", "0.0.0.0", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(low)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def validate_download_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("unsupported scheme")
    if not parsed.hostname or is_blocked_host(parsed.hostname):
        raise ValueError("blocked host")
    return url


MAX_ARCHIVE_FILES = 100
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024


def safe_extract_zip(archive: Path, dest: Path) -> list[str]:
    """Extract only paths that stay inside dest. Never executes files."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    written = []
    total = 0
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_FILES:
            raise ValueError("archive has too many files")
        for info in infos:
            target = (dest / info.filename).resolve()
            if not str(target).startswith(str(root)):
                raise ValueError(f"archive path escapes: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            data = zf.read(info.filename)
            total += len(data)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("archive expands beyond limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(info.filename)
    return written
