"""HTTPS and SSRF checks for research. Reuses Feature 6 URL validation."""

from __future__ import annotations

from jarvis.resources.downloader import DownloadError, validate_url


def validate_research_url(url: str) -> str:
    if not url.startswith("https://"):
        raise ValueError("research source must use https")
    try:
        return validate_url(url, allow_private=False)
    except DownloadError as exc:
        raise ValueError(f"unsafe research url: {exc.message}") from exc
