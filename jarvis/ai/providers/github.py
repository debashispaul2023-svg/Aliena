"""GitHub repository search provider (documented REST API).

Does not clone, install, or execute repositories.
Optional GITHUB_TOKEN via environment for higher rate limits — never logged.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import requests


class GitHubSearchAdapter:
    """Search public GitHub repositories.

    mode is LIVE only when a successful API response is parsed.
    """

    mode = "LIVE"
    ENDPOINT = "https://api.github.com/search/repositories"

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 1,
        token: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._session = session or requests.Session()
        self.last_error: Optional[str] = None
        self.last_status: Optional[int] = None

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "JarvisResourceFinder/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.last_error = None
        self.last_status = None
        q = (query or "").strip()
        if not q:
            return []

        params = {
            "q": q,
            "per_page": max(1, min(int(limit), 30)),
            "sort": "stars",
            "order": "desc",
        }
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(
                    self.ENDPOINT,
                    params=params,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                self.last_status = resp.status_code
                if resp.status_code == 401:
                    self.last_error = "Authentication failed"
                    return []
                if resp.status_code == 403:
                    # rate limit or forbidden — do not leak token
                    self.last_error = "Forbidden or rate limited"
                    if attempt < self.max_retries:
                        continue
                    return []
                if resp.status_code == 429:
                    self.last_error = "Rate limit exceeded"
                    if attempt < self.max_retries:
                        continue
                    return []
                if resp.status_code >= 400:
                    self.last_error = f"HTTP {resp.status_code}"
                    return []
                try:
                    data = resp.json()
                except ValueError:
                    self.last_error = "Malformed JSON response"
                    return []
                return self._parse(data, limit=limit)
            except requests.Timeout as exc:
                last_exc = exc
                self.last_error = "Request timed out"
                if attempt < self.max_retries:
                    continue
                return []
            except requests.RequestException as exc:
                last_exc = exc
                self.last_error = f"Network error: {exc}"
                if attempt < self.max_retries:
                    continue
                return []
        if last_exc and not self.last_error:
            self.last_error = str(last_exc)
        return []

    def _parse(self, data: Any, limit: int = 5) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            self.last_error = "Unexpected response shape"
            return []
        items = data.get("items")
        if items is None:
            self.last_error = "Missing items field"
            return []
        if not isinstance(items, list):
            self.last_error = "Malformed items"
            return []
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("full_name") or item.get("name") or ""
            url = item.get("html_url") or ""
            if not name and not url:
                continue
            if url and not str(url).startswith("http"):
                continue
            license_info = item.get("license") if isinstance(item.get("license"), dict) else None
            license_spdx = None
            if license_info:
                license_spdx = license_info.get("spdx_id") or license_info.get("name")
            out.append(
                {
                    "title": str(name),
                    "url": str(url) if url else "",
                    "description": str(item.get("description") or ""),
                    "source": "github",
                    "kind": "repo",
                    "version": str(item.get("default_branch") or "") or None,
                    "license": license_spdx,
                    "stars": item.get("stargazers_count"),
                    "language": item.get("language"),
                    "updated_at": item.get("updated_at"),
                }
            )
            if len(out) >= limit:
                break
        return out
