"""PyPI package search provider (official JSON / search endpoints).

Does not install packages. Does not invent compatibility claims.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import requests


class PyPISearchAdapter:
    """Search PyPI packages via the public JSON API and warehouse search.

    Primary path: https://pypi.org/pypi/<name>/json for exact names.
    Fallback: https://pypi.org/search/?q=... is HTML — we use the
    simple JSON project endpoint when query looks like a package name,
    and the warehouse search API if available.
    """

    mode = "LIVE"
    JSON_URL = "https://pypi.org/pypi/{name}/json"
    # Undocumented but widely used public search JSON used by tools;
    # we also try exact project lookup first which is fully official.
    SEARCH_URL = "https://pypi.org/search/"

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 1,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._session = session or requests.Session()
        self.last_error: Optional[str] = None
        self.last_status: Optional[int] = None

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.last_error = None
        self.last_status = None
        q = (query or "").strip()
        if not q:
            return []

        # Prefer exact project JSON when query is a single token package-like name
        token = q.split()[0]
        results: list[dict[str, Any]] = []
        exact = self._fetch_project(token)
        if exact:
            results.append(exact)

        # Supplement with search page parse (lightweight) only if needed
        if len(results) < limit:
            extra = self._search_html(q, limit=limit)
            seen = {r.get("url") for r in results}
            for row in extra:
                if row.get("url") in seen:
                    continue
                results.append(row)
                seen.add(row.get("url"))
                if len(results) >= limit:
                    break

        return results[:limit]

    def _fetch_project(self, name: str) -> Optional[dict[str, Any]]:
        # package names are case-insensitive; normalize mildly
        safe = name.strip().lower()
        if not safe or not all(c.isalnum() or c in "-_." for c in safe):
            return None
        url = self.JSON_URL.format(name=quote(safe))
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                self.last_status = resp.status_code
                if resp.status_code == 404:
                    return None
                if resp.status_code == 429:
                    self.last_error = "Rate limit exceeded"
                    if attempt < self.max_retries:
                        continue
                    return None
                if resp.status_code >= 400:
                    self.last_error = f"HTTP {resp.status_code}"
                    return None
                try:
                    data = resp.json()
                except ValueError:
                    self.last_error = "Malformed JSON response"
                    return None
                return self._parse_project(data)
            except requests.Timeout:
                self.last_error = "Request timed out"
                if attempt < self.max_retries:
                    continue
                return None
            except requests.RequestException as exc:
                self.last_error = f"Network error: {exc}"
                if attempt < self.max_retries:
                    continue
                return None
        return None

    def _parse_project(self, data: Any) -> Optional[dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        info = data.get("info")
        if not isinstance(info, dict):
            return None
        name = info.get("name") or ""
        project_url = info.get("project_url") or info.get("package_url") or ""
        if not project_url and name:
            project_url = f"https://pypi.org/project/{name}/"
        if not name:
            return None
        version = info.get("version")
        requires_python = info.get("requires_python")
        license_meta = info.get("license") or None
        # classifiers may include license — leave unknown if empty
        return {
            "title": str(name),
            "url": str(project_url),
            "description": str(info.get("summary") or ""),
            "source": "pypi",
            "kind": "package",
            "version": str(version) if version else None,
            "license": str(license_meta) if license_meta else None,
            "requires_python": requires_python,
            "home_page": info.get("home_page") or info.get("project_urls", {}).get("Homepage")
            if isinstance(info.get("project_urls"), dict)
            else info.get("home_page"),
        }

    def _search_html(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Parse package names from PyPI search HTML; no invented metadata."""
        import re
        from html import unescape

        params = {"q": query}
        try:
            resp = self._session.get(
                self.SEARCH_URL,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "JarvisResourceFinder/1.0"},
            )
            self.last_status = resp.status_code
            if resp.status_code >= 400:
                if not self.last_error:
                    self.last_error = f"HTTP {resp.status_code}"
                return []
            html = resp.text or ""
        except requests.RequestException as exc:
            if not self.last_error:
                self.last_error = f"Network error: {exc}"
            return []

        # Package links: /project/<name>/
        pattern = re.compile(
            r'href="https://pypi\.org/project/([^"/]+)/?"[^>]*>\s*([^<]+)',
            re.I,
        )
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for m in pattern.finditer(html):
            name = unescape(m.group(1).strip())
            title = unescape(m.group(2).strip()) or name
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append(
                {
                    "title": title,
                    "url": f"https://pypi.org/project/{name}/",
                    "description": "",
                    "source": "pypi",
                    "kind": "package",
                    "version": None,  # unknown from HTML snippet
                    "license": None,
                }
            )
            if len(out) >= limit:
                break
        return out
