"""C7 DebugManager: diagnose static findings, propose fixes, apply only SAFE ones, bounded retries.

Auto-applied (generated, unmodified files only, backed up): create a missing css/js stub, strip trailing commas
from invalid JSON, declare a well-known Python package in requirements.txt. Everything else is a proposal.
Nothing is executed. A checkpoint is taken before any correction."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from jarvis.creator.audit import AuditLogger
from jarvis.creator.testing_engine import ProjectChecker
from jarvis.creator.workspace_manager import CreatorWorkspaceError, CreatorWorkspaceManager

MAX_ROUNDS = 3
MAX_FIXES_PER_ROUND = 25
KNOWN_PACKAGES = {"requests": "requests", "pydantic": "pydantic", "fastapi": "fastapi", "httpx": "httpx",
                  "pytest": "pytest", "pygame": "pygame", "uvicorn": "uvicorn", "yaml": "pyyaml", "numpy": "numpy"}
_STUBS = {".css": "/* generated stub: replace with real styles */\n", ".js": "// generated stub: replace with real code\n"}


def strip_trailing_commas(text: str) -> Optional[str]:
    """Remove commas before } or ] outside strings. Returns None unless the result parses as JSON."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
            out.append(c)
        else:
            out.append(c)
        i += 1
    fixed = "".join(out)
    try:
        json.loads(fixed)
    except ValueError:
        return None
    return fixed


class DebugManager:
    def __init__(self, ws: CreatorWorkspaceManager, audit: Optional[AuditLogger] = None) -> None:
        self.ws = ws
        self.audit = audit or ws.audit
        self.checker = ProjectChecker(ws)

    # ---- diagnosis ----
    def diagnose(self, pid: str, report: dict[str, Any]) -> list[dict[str, Any]]:
        tracked = set(self.ws.manifest(pid))
        out = []
        for f in report["findings"]:
            if f["severity"] != "error":
                continue
            d = {"finding": f["id"], "check": f["check"], "path": f["path"], "cause": f["message"],
                 "action": "manual", "auto": False, "detail": "review and fix manually"}
            if f["check"] == "references":
                ref = f["data"].get("resolved", "")
                ext = "." + ref.rsplit(".", 1)[-1] if "." in ref else ""
                if ext in _STUBS and ref and not ref.startswith(".."):
                    d.update(action="create_stub", auto=True, target=ref, detail=f"create stub {ref}")
            elif f["check"] == "imports":
                pass
            elif f["check"] == "syntax" and f["path"].endswith(".json") and f["path"] in tracked:
                d.update(action="strip_trailing_commas", auto=True, target=f["path"], detail="remove trailing commas")
            elif f["check"] == "dependencies" and f["data"].get("language") == "python":
                name = f["data"]["name"]
                if name in KNOWN_PACKAGES:
                    d.update(action="declare_python_dependency", auto=True, target="requirements.txt",
                             dist=KNOWN_PACKAGES[name], detail=f"declare {KNOWN_PACKAGES[name]} (version unpinned, not installed)")
                else:
                    d["detail"] = f"declare a distribution providing '{name}' (unknown mapping, not auto-fixed)"
            elif f["check"] == "dependencies":
                d["detail"] = f"add '{f['data']['name']}' with a pinned version to package.json (version unknown offline)"
            elif f["check"] == "secrets":
                d["detail"] = "remove the credential, rotate it if real; never auto-edited"
            elif f["check"] == "integrity":
                d["detail"] = "file changed outside Creator: restore from a checkpoint (approval needed) or accept the change"
            out.append(d)
        return out

    # ---- application ----
    def _apply(self, pid: str, d: dict[str, Any]) -> bool:
        a, tgt = d["action"], d.get("target", "")
        if a == "create_stub":
            if tgt in self.ws.manifest(pid):
                return False
            self.ws.write_file(pid, tgt, _STUBS["." + tgt.rsplit(".", 1)[-1]], actor="debug")
            return True
        if a == "strip_trailing_commas":
            fixed = strip_trailing_commas(self.ws.read_file(pid, tgt).decode("utf-8"))
            if fixed is None:
                return False
            self.ws.correct_generated_file(pid, tgt, fixed, actor="debug")
            return True
        if a == "declare_python_dependency":
            if "requirements.txt" in self.ws.manifest(pid):
                cur = self.ws.read_file(pid, "requirements.txt").decode("utf-8")
                if re.search(rf"(?im)^{re.escape(d['dist'])}\b", cur):
                    return False
                self.ws.correct_generated_file(pid, "requirements.txt", cur.rstrip("\n") + ("\n" if cur.strip() else "") + d["dist"] + "\n", actor="debug")
            else:
                self.ws.write_file(pid, "requirements.txt", d["dist"] + "\n", actor="debug")
            return True
        return False

    def run(self, pid: str, max_rounds: int = MAX_ROUNDS) -> dict[str, Any]:
        max_rounds = max(1, min(int(max_rounds), MAX_ROUNDS))
        before = self.checker.check(pid)
        run: dict[str, Any] = {"project_id": pid, "started_at": datetime.now(timezone.utc).isoformat(), "rounds": [],
                               "errors_before": sum(1 for f in before["findings"] if f["severity"] == "error"),
                               "checkpoint": None, "commands_executed": []}
        report, seen = before, set()
        if run["errors_before"]:
            run["checkpoint"] = self.ws.create_checkpoint(pid, "pre-debug", "debug", skip_missing=True)
        for n in range(1, max_rounds + 1):
            errors = [f for f in report["findings"] if f["severity"] == "error"]
            if not errors:
                break
            signature = frozenset(f["id"] for f in errors)
            if signature in seen:  # no progress: stop instead of looping
                run["stopped"] = "no progress"
                break
            seen.add(signature)
            diags = self.diagnose(pid, report)
            applied, skipped = [], []
            for d in [x for x in diags if x["auto"]][:MAX_FIXES_PER_ROUND]:
                try:
                    (applied if self._apply(pid, d) else skipped).append({"finding": d["finding"], "action": d["action"], "target": d.get("target")})
                except CreatorWorkspaceError as exc:
                    skipped.append({"finding": d["finding"], "action": d["action"], "error": str(exc)[:120]})
            run["rounds"].append({"round": n, "errors": len(errors), "applied": applied, "skipped": skipped,
                                  "proposals": [x for x in diags if not x["auto"]]})
            if not applied:
                run["stopped"] = "no applicable automatic fixes"
                break
            report = self.checker.check(pid)
        else:
            run["stopped"] = "retry limit reached"
        remaining = [f for f in report["findings"] if f["severity"] == "error"]
        run.update(errors_after=len(remaining), remaining=[f for f in remaining],
                   resolved=not remaining, regression={"integrity_ok": self.ws.verify_integrity(pid)["ok"]},
                   ai_generated=False)
        seq = len(self.ws.list_control_records(pid, "debug")) + 1
        self.ws.save_control_record(pid, "debug", f"debug_{seq:04d}", run)
        self.audit.record(pid, "debug", "debug_run", "resolved" if run["resolved"] else "unresolved",
                          f"before={run['errors_before']} after={run['errors_after']} rounds={len(run['rounds'])}")
        return run
