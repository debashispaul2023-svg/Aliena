"""UI-framework-agnostic view-model for the Creator panel (keyboard-first, voice optional).

Provides every section the product spec lists as plain JSON-serialisable data so any front end (the existing
PyQt shell, a CLI, tests) can render it. It does not touch the avatar/emotion system except through optional callbacks."""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from jarvis.creator.engine import STAGES, STAGE_AGENT, CreationResult, CreatorEngine

KEYBINDINGS = {"ctrl+n": "new_project", "ctrl+enter": "start_build", "f5": "refresh", "ctrl+t": "show_test_results",
               "ctrl+e": "show_errors", "ctrl+p": "show_preview", "ctrl+d": "show_delivery", "ctrl+f": "show_files", "escape": "close_panel"}
AVATAR_FOR = {"running": "thinking", "delivered": "happy", "static_verified": "happy", "failed": "sad", "failed_static": "sad",
              "refused": "sad", "needs_clarification": "confused", "unsupported": "confused", "idle": "idle"}


class CreatorUIModel:
    def __init__(self, engine: CreatorEngine, avatar_state: Optional[Callable[[str], None]] = None) -> None:
        self.engine = engine
        self.avatar_state = avatar_state
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {"phase": "idle", "request": "", "project_id": None, "progress": [], "result": None}
        self.engine.on_event = self._on_event

    def _avatar(self, key: str) -> None:
        if self.avatar_state:
            try:
                self.avatar_state(AVATAR_FOR.get(key, "idle"))
            except Exception:
                pass

    def _on_event(self, ev: dict[str, Any]) -> None:
        with self._lock:
            self.state["progress"].append({k: ev[k] for k in ("stage", "agent", "status", "detail", "step", "of")})

    # ---- actions
    def project_types(self) -> list[dict[str, str]]:
        return ([{"id": c["composer_id"], "kind": "composer", "project_type": c["project_type"], "support": c["support_level"]} for c in self.engine.gen.composers.list()]
                + [{"id": t["template_id"], "kind": "template", "project_type": t["project_type"], "support": t["support_level"]} for t in self.engine.gen.registry.list()])

    def new_project(self, request: str, **kw: Any) -> CreationResult:
        with self._lock:
            self.state.update(phase="running", request=request, project_id=None, progress=[], result=None)
        self._avatar("running")
        res = self.engine.create(request, **kw)
        with self._lock:
            self.state.update(phase=res.status, project_id=res.project_id, result=res)
        self._avatar(res.status)
        return res

    # ---- sections
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self.state)
            progress = list(st["progress"])
        res: Optional[CreationResult] = st["result"]
        done = {p["stage"] for p in progress if p["status"] not in ("failed", "refused", "unsupported", "needs_clarification")}
        static_ok = any(p["stage"] == "static_test" and p["status"] == "passed" for p in progress)
        expected = set(STAGES) - ({"debug", "retest"} if static_ok else set())
        snap: dict[str, Any] = {
            "new_project": {"project_types": self.project_types(), "requirements_input": st["request"], "keyboard": KEYBINDINGS},
            "planning_view": res.plan if res else {},
            "assumptions": res.assumptions if res else [],
            "build_progress": {"phase": st["phase"], "percent": round(100 * len(done & expected) / len(expected)), "steps": progress},
            "agent_activity": [{"agent": p["agent"], "stage": p["stage"], "status": p["status"]} for p in progress],
            "file_explorer": self.engine.file_tree(st["project_id"]) if st["project_id"] else {},
            "test_results": res.test_report.get("categories", {}) if res else {},
            "error_reports": [f for f in (res.test_report.get("findings", []) if res else []) if f["severity"] == "error"] + ([{"message": res.error}] if res and res.error else []),
            "preview_status": res.preview if res else {},
            "delivery_summary": ({k: res.delivery.get(k) for k in ("version", "zip", "zip_sha256", "file_count", "status", "runtime_verified", "published", "deployed")}
                                 if res and res.delivery else {}),
            "ai_assist": res.ai_assist if res else {},
            "notices": ["Generated code is NOT executed: execution is blocked until OS-level isolation is verified."],
        }
        if res:
            snap["message"] = res.message
        return snap
