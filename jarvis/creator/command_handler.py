"""Typed/spoken command handler for the Creator Engine, matching Aliena's `handler.handle(query) -> bool` pattern."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

from jarvis.core.approval import from_confirmation
from jarvis.creator.engine import CreatorEngine
from jarvis.creator.ui_model import CreatorUIModel

_NOUNS = (r"website|web site|web app|webpage|landing page|rest api|api|backend|fastapi|python (?:app|tool|program|script|cli)|"
          r"command[- ]line tool|cli tool|mobile app|android app|ios app|game|react app|react website|next\.?js|desktop app|"
          r"database schema|documentation")
CREATE_RE = re.compile(rf"^\s*(?:please\s+|can you\s+|jarvis\s+|aliena\s+)?(?:create|build|make|generate)\b.*\b(?:{_NOUNS})\b", re.I)
EXPORT_RE = re.compile(r"^\s*confirm export (?:project )?(cre_[0-9a-f]{16}|last) to (.+?)\s*$", re.I)


def build_creator_handler(root: Path, speak: Optional[Callable[[str], None]] = None, status: Optional[Callable[[str], None]] = None,
                          avatar_state: Optional[Callable[[str], None]] = None, router: Any = None) -> "CreatorCommandHandler":
    engine = CreatorEngine(Path(root), router=router, audit_path=Path(root) / "creator_audit.jsonl")
    return CreatorCommandHandler(engine, speak=speak, status=status, avatar_state=avatar_state)


class CreatorCommandHandler:
    def __init__(self, engine: CreatorEngine, speak=None, status=None, avatar_state=None) -> None:
        self.engine = engine
        self.speak = speak or (lambda m: None)
        self.status = status or (lambda m: None)
        self.ui = CreatorUIModel(engine, avatar_state)
        self.last_pid: Optional[str] = None
        self.engine_prev_cb = None
        self.ui.engine.on_event = self._relay(self.ui._on_event)

    def _relay(self, inner):
        def cb(ev):
            inner(ev)
            self.status(f"Creator {ev['step']}/{ev['of']} {ev['stage']}: {ev['status']}")
        return cb

    def _pid(self, token: Optional[str]) -> Optional[str]:
        token = (token or "").strip()
        if token in ("", "last"):
            return self.last_pid
        return token if re.fullmatch(r"cre_[0-9a-f]{16}", token) else None

    def handle(self, query: str) -> bool:
        q = (query or "").strip()
        low = q.lower()
        if m := EXPORT_RE.match(q):
            return self._export(m.group(1), m.group(2))
        if low in ("creator projects", "list creator projects", "show creator projects"):
            ps = self.engine.projects()
            self.speak(f"{len(ps)} Creator projects." + "".join(f" {p['name']} ({p['project_type']})." for p in ps[:5]))
            return True
        m = re.match(r"^creator (status|files|report|preview|package)(?: (\S+))?$", low)
        if m:
            return self._info(m.group(1), self._pid(m.group(2)))
        if CREATE_RE.match(q):
            self.status("Creator: planning...")
            res = self.ui.new_project(q)
            self.last_pid = res.project_id or self.last_pid
            extra = f" Project id {res.project_id}." if res.project_id else ""
            self.speak(res.message + extra)
            return True
        return False

    def _info(self, what: str, pid: Optional[str]) -> bool:
        if not pid:
            self.speak("No Creator project selected. Create one first or give a project id.")
            return True
        try:
            if what == "files":
                inv = self.engine.ws.inventory(pid)
                self.speak(f"{len(inv)} files: " + ", ".join(i["path"] for i in inv[:8]) + (" ..." if len(inv) > 8 else ""))
            elif what == "report":
                names = self.engine.ws.list_control_records(pid, "reports")
                rep = self.engine.ws.load_control_record(pid, "reports", names[-1]) if names else None
                self.speak(f"Latest test report: {rep['completion']['status']}. Runtime tests were not run (blocked)." if rep else "No test report yet.")
            elif what == "preview":
                r = self.engine.preview.build_static_preview(pid)
                self.speak("Static preview built; it has no scripts." if r.get("built") else f"Preview not available: {r.get('reason') or 'checks failed'}")
            elif what == "package":
                from jarvis.creator.delivery_manager import DeliveryRefused
                try:
                    d = self.engine.delivery.package(pid)
                    self.speak(f"Packaged version {d['version']}: {d['zip']}. Not published or deployed.")
                except DeliveryRefused as exc:
                    self.speak(f"Delivery refused: {exc}")
            else:
                m = self.engine.ws.metadata(pid)
                self.speak(f"{m['name']} ({m['project_type']}), {len(self.engine.ws.manifest(pid))} files.")
        except Exception as exc:
            self.speak(f"Creator error: {type(exc).__name__}")
        return True

    def _export(self, token: str, dest: str) -> bool:
        pid = self._pid(token)
        if not pid:
            self.speak("No such Creator project.")
            return True
        approval = from_confirmation("export_delivery", pid, True, reviewer="user")  # the typed 'confirm' phrase is the approval
        try:
            versions = len(self.engine.ws.list_control_records(pid, "delivery"))
            path = self.engine.delivery.export(pid, versions, dest.strip().strip('"'), approval=approval)
            self.speak(f"Exported to {path}.")
        except Exception as exc:
            self.speak(f"Export failed: {exc}")
        return True
