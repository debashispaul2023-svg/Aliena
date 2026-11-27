"""C8 PreviewManager: SAFE static preview only.

A preview is a set of self-contained, script-free HTML files written next to the project (never served,
no server started, nothing executed). Anything needing code execution (React/Next dev server, FastAPI, Python,
games, mobile) is reported as BLOCKED - there is no host-execution fallback."""

from __future__ import annotations

import base64
import hashlib
import html
import posixpath
import re
from html.parser import HTMLParser
from typing import Any, Optional

from jarvis.creator.audit import AuditLogger
from jarvis.creator.security_gate import SecurityGate
from jarvis.creator.testing_engine import ProjectChecker
from jarvis.creator.workspace_manager import CreatorWorkspaceError, CreatorWorkspaceManager

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp"}
_DROP = {"script", "iframe", "object", "embed", "frame", "frameset", "applet", "base", "meta_refresh"}
_VOID = {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr", "base"}
BLOCK_REASON = "previewing this project type requires executing code (dev server/build/runtime): BLOCKED, no host fallback"


def sanitize_css(css: str) -> str:
    css = re.sub(r"@import[^;]*;", "", css, flags=re.I)
    return re.sub(r"url\(\s*(?!['\"]?data:)[^)]*\)", 'url("data:,")', css, flags=re.I)


class _Sanitizer(HTMLParser):
    """Re-emits HTML while removing scripts/embeds/event handlers and inlining local CSS and images."""

    def __init__(self, resolve):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.resolve = resolve  # (ref) -> (kind, payload) ; kind in css|img|none
        self.skip: Optional[str] = None
        self.removed: list[str] = []
        self.has_csp_slot = False

    def _attrs(self, attrs):
        return "".join(f' {k}="{html.escape(v if v is not None else "", quote=True)}"' if v is not None else f" {k}" for k, v in attrs)

    def handle_starttag(self, tag, attrs):
        if self.skip:
            return
        if tag in _DROP:
            self.removed.append(f"<{tag}>")
            if tag not in _VOID:
                self.skip = tag
            return
        d = {k: v for k, v in attrs}
        clean = []
        for k, v in attrs:
            lk = k.lower()
            if lk.startswith("on"):
                self.removed.append(f"{lk} attribute")
                continue
            if lk in ("href", "src", "action", "formaction", "poster", "data", "srcset", "style") and v:
                if lk == "style":
                    clean.append((k, sanitize_css(v)))
                    continue
                if re.match(r"^\s*(javascript|vbscript):", v, re.I):
                    self.removed.append(f"{lk}={v[:30]}")
                    continue
            clean.append((k, v))
        if tag == "link" and (d.get("rel") or "").lower() == "stylesheet":
            kind, payload = self.resolve(d.get("href") or "")
            if kind == "css":
                self.out.append(f"<style>{payload}</style>")
            else:
                self.removed.append(f"stylesheet {d.get('href')}")
            return
        if tag == "link":
            self.removed.append(f"<link rel={d.get('rel')}>")
            return
        if tag == "img":
            kind, payload = self.resolve(d.get("src") or "")
            clean = [(k, v) for k, v in clean if k.lower() not in ("src", "srcset")]
            if kind == "img":
                clean.append(("src", payload))
            else:
                self.removed.append(f"image {d.get('src')}")
        elif tag == "form":
            clean = [(k, v) for k, v in clean if k.lower() != "action"]
        if tag == "head":
            self.out.append(f"<head><meta http-equiv=\"Content-Security-Policy\" content=\"{html.escape(CSP)}\">")
            self.has_csp_slot = True
            return
        self.out.append(f"<{tag}{self._attrs(clean)}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip:
                self.skip = None
            return
        if tag in _VOID or tag in _DROP:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)

    def handle_entityref(self, name):
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip:
            self.out.append(f"&#{name};")

    def handle_decl(self, decl):
        if not self.skip and decl.lower().startswith("doctype"):
            self.out.append("<!DOCTYPE html>")

    def handle_comment(self, data):
        pass


class PreviewManager:
    def __init__(self, ws: CreatorWorkspaceManager, gate: SecurityGate, audit: Optional[AuditLogger] = None) -> None:
        self.ws, self.gate, self.audit = ws, gate, audit or ws.audit
        self.checker = ProjectChecker(ws)

    def status(self, pid: str) -> dict[str, Any]:
        tracked = set(self.ws.manifest(pid))
        pages = sorted(t for t in tracked if t.endswith(".html") and "/" not in t)
        program = lambda t: t.endswith(".py") and not t.startswith(("tests/", "test_")) and "/tests/" not in t
        framework = "package.json" in tracked or any(program(t) for t in tracked)
        if pages and not framework:
            return {"project_id": pid, "supported": True, "mode": "static_no_script", "pages": pages,
                    "note": "scripts are removed in the preview, so interactivity is not shown"}
        return {"project_id": pid, "supported": False, "mode": "blocked", "pages": [], "reason": BLOCK_REASON}

    def build_static_preview(self, pid: str, actor: str = "preview") -> dict[str, Any]:
        st = self.status(pid)
        if not st["supported"]:
            self.audit.record(pid, actor, "preview", "blocked", st["reason"][:100])
            return {**st, "built": False, "files": [], "server_started": False, "executed": False}
        if not self.gate.check(pid, actor, "run_static_checks").allowed:
            raise CreatorWorkspaceError("preview denied")
        report = self.checker.check(pid)
        blocking = [f for f in report["findings"] if f["severity"] == "error" and f["check"] in ("syntax", "references", "secrets", "integrity")]
        if blocking:
            self.audit.record(pid, actor, "preview", "refused", f"{len(blocking)} blocking findings")
            return {**st, "built": False, "refused": True, "findings": blocking[:20], "files": [],
                    "server_started": False, "executed": False}
        tracked = set(self.ws.manifest(pid))
        self.ws.clear_artifacts(pid, "preview")
        files, removed_all, total = [], [], 0
        for page in st["pages"]:
            def resolve(ref, _page=page):
                if re.match(r"^(https?:)?//|^[a-z][a-z0-9+.-]*:", ref, re.I):
                    return "none", ""
                target = posixpath.normpath(posixpath.join(posixpath.dirname(_page), ref.split("#")[0].split("?")[0]))
                if target not in tracked or target.startswith(".."):
                    return "none", ""
                ext = posixpath.splitext(target)[1].lower()
                raw = self.ws.read_file(pid, target)
                if ext == ".css":
                    return "css", sanitize_css(raw.decode("utf-8", "replace"))
                if ext in _MIME:
                    return "img", f"data:{_MIME[ext]};base64," + base64.b64encode(raw).decode()
                return "none", ""
            san = _Sanitizer(resolve)
            san.feed(self.ws.read_file(pid, page).decode("utf-8"))
            san.close()
            body = "".join(san.out)
            if not san.has_csp_slot:
                body = f"<meta http-equiv=\"Content-Security-Policy\" content=\"{html.escape(CSP)}\">" + body
            data = body.encode("utf-8")
            total += len(data)
            if total > MAX_PREVIEW_BYTES:
                raise CreatorWorkspaceError("preview too large")
            name = page.replace("/", "_")
            path = self.ws.write_artifact(pid, "preview", name, data, overwrite=True, actor=actor)
            files.append({"path": path, "source": page, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
            removed_all += [f"{page}: {r}" for r in san.removed]
        self.audit.record(pid, actor, "preview", "built", f"{len(files)} pages, {len(removed_all)} removals")
        return {**st, "built": True, "files": files, "removed": removed_all, "csp": CSP,
                "server_started": False, "executed": False,
                "open_hint": "open the preview files in a browser from disk; they are inert (no scripts, no network)"}
