"""Live web search adapters for Resource Finder.

DuckDuckGoHTMLAdapter uses the public HTML endpoint via requests.
No API key required. Results are real network responses when LIVE.
Never invents URLs. Never installs packages.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Optional
from urllib.parse import quote_plus, urljoin

import requests


class DuckDuckGoHTMLAdapter:
    """Search DuckDuckGo HTML results.

    mode is LIVE only when a successful HTTP response yields parsed hits.
    On network/parse failure, returns [] and leaves mode reporting to caller.
    """

    mode = "LIVE"
    ENDPOINT = "https://html.duckduckgo.com/html/"

    def __init__(self, timeout: float = 10.0, max_retries: int = 1) -> None:
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.last_error: Optional[str] = None
        self.last_status: Optional[int] = None

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.last_error = None
        self.last_status = None
        q = (query or "").strip()
        if not q:
            return []

        headers = {
            "User-Agent": "JarvisResourceFinder/1.0 (+local; educational)",
            "Accept": "text/html",
        }
        data = {"q": q, "b": ""}
        last_exc: Optional[Exception] = None
        text = ""
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.ENDPOINT,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                )
                self.last_status = resp.status_code
                if resp.status_code == 200:
                    text = resp.text or ""
                    break
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    continue
                self.last_error = f"HTTP {resp.status_code}"
                return []
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
        if not text:
            if last_exc and not self.last_error:
                self.last_error = str(last_exc)
            return []

        return self._parse_html(text, limit=limit)

    def _parse_html(self, html: str, limit: int = 5) -> list[dict[str, Any]]:
        """Parse DDG HTML result blocks without inventing links."""
        results: list[dict[str, Any]] = []
        # Result links typically in <a class="result__a" href="...">title</a>
        pattern = re.compile(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pat = re.compile(
            r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|'
            r'<td[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</td>',
            re.IGNORECASE | re.DOTALL,
        )
        snippets = [
            unescape(re.sub(r"<[^>]+>", " ", (m.group(1) or m.group(2) or ""))).strip()
            for m in snippet_pat.finditer(html)
        ]
        for i, m in enumerate(pattern.finditer(html)):
            if len(results) >= limit:
                break
            href = unescape(m.group(1)).strip()
            title = unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip()
            # DDG sometimes wraps redirects: //duckduckgo.com/l/?uddg=<url>
            if "uddg=" in href:
                from urllib.parse import parse_qs, urlparse

                qs = parse_qs(urlparse(href).query)
                real = qs.get("uddg", [None])[0]
                if real:
                    href = real
            if href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http"):
                continue
            snip = snippets[i] if i < len(snippets) else ""
            results.append(
                {
                    "title": title or href,
                    "url": href,
                    "description": snip,
                    "source": "duckduckgo",
                    "kind": "docs" if any(
                        x in href for x in ("docs.", "readthedocs", "developer.")
                    ) else "other",
                }
            )
        if not results:
            # Alternative pattern used by some DDG responses
            alt = re.compile(
                r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>',
                re.I | re.S,
            )
            for m in alt.finditer(html):
                if len(results) >= limit:
                    break
                href = unescape(m.group(1)).strip()
                title = unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip()
                if "uddg=" in href:
                    from urllib.parse import parse_qs, urlparse

                    qs = parse_qs(urlparse(href).query)
                    real = qs.get("uddg", [None])[0]
                    if real:
                        href = real
                if href.startswith("//"):
                    href = "https:" + href
                if href.startswith("http"):
                    results.append(
                        {
                            "title": title or href,
                            "url": href,
                            "description": "",
                            "source": "duckduckgo",
                            "kind": "other",
                        }
                    )
        return results
