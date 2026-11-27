"""Gemini accounts Settings: view-model, text renderer, command handler and CLI.

Shows only Configured / Missing per slot (never any part of a key). Network requests happen only when the
user explicitly runs a check command."""

from __future__ import annotations

import re
import sys
import time
from typing import Any, Callable, Optional

from jarvis.ai.gemini_accounts import ENV_VARS, GeminiAccountManager, LEGACY_ENV_VAR, shared_manager

_HEALTH_TEXT = {
    "unverified": "not verified yet (no successful request so far)", "ok": "verified by a real successful request",
    "invalid_key": "API key rejected", "permission_denied": "access denied", "model_not_found": "model not available",
    "rate_limited": "rate limited", "server_error": "Google service error", "network_error": "network error",
    "timeout": "timed out", "bad_request": "last request rejected", "empty_response": "last response empty",
    "blocked_content": "last response blocked", "unknown_http": "unexpected response", "duplicate": "duplicate of another slot",
    "malformed": "malformed value", "missing": "no key set",
}


class GeminiSettings:
    def __init__(self, manager: Optional[GeminiAccountManager] = None, clock: Callable[[], float] = time.time) -> None:
        self.manager = manager or shared_manager()
        self._clock = clock

    def rows(self) -> list[dict[str, Any]]:
        rows = []
        for s in self.manager.slots():
            state = "Configured" if s["configured"] else "Missing"
            if s["config_state"] == "malformed":
                health = "malformed value: " + s["problem"]
            elif s["config_state"] == "missing":
                health = f"set {s['env_var']} in the environment"
            else:
                health = _HEALTH_TEXT.get(s["status"], s["status"])
                if s["verified_at"] and s["status"] == "ok":
                    health += " at " + time.strftime("%H:%M:%S", time.localtime(s["verified_at"]))
                if s["cooldown_remaining_s"] > 0:
                    health += f"; cooling down {int(s['cooldown_remaining_s']) + 1}s (no requests sent)"
                if s["blocked"]:
                    health += "; blocked until the key is fixed and re-checked"
            rows.append({"slot": s["slot"], "label": f"Account slot {s['slot']}", "state": state, "env_var": s["env_var"],
                         "active": s["active"], "health": health, "usage": s["usage"], "duplicate_of": s["duplicate_of"]})
        return rows

    def render_text(self, detailed: bool = True) -> str:
        lines = [f"{r['label']}: {r['state']}" + (" (active)" if r["active"] else "") for r in self.rows()]
        if not detailed:
            return "\n".join(lines)
        h = self.manager.health()
        lines += ["", f"Model: {h['model']} (fixed; never switched automatically)", f"Overall: {h['overall']}"]
        for r in self.rows():
            u = r["usage"]
            lines.append(f"- slot {r['slot']}: {r['health']}")
            if u["requests"]:
                lines.append(f"    requests {u['requests']}, ok {u['successes']}, retries {u['retries']}, rate-limit events "
                             f"{u['rate_limit_events']}, tokens {u['tokens']['total_tokens']}, errors {u['errors'] or 'none'}")
        if any(r["usage"]["requests"] for r in self.rows()):
            lines.append("Quota remaining: not exposed by the Gemini API.")
        if self.manager.notes:
            lines += ["Notes:"] + [f"- {n}" for n in self.manager.notes]
        lines.append("Keys are read from environment variables only and are never shown. Aliena never switches keys or models automatically.")
        return "\n".join(lines)

    def check(self, slot: Optional[int] = None, deep: bool = False) -> str:
        n = slot or self.manager.active_slot
        if n is None:
            return "No Gemini key is configured. Set GEMINI_API_KEY_1, _2 or _3."
        res = self.manager.check_slot(n, deep=deep)
        if res.ok:
            return (f"Slot {n}: connection verified by a real {'generation' if deep else 'model lookup'} request "
                    f"to {res.model}.")
        return f"Slot {n}: NOT verified. {res.error}"

    def use(self, slot: int) -> str:
        return self.manager.select_slot(slot)[1]

    def reload(self) -> str:
        self.manager.reload_from_env()
        return "Re-read the environment. Run a check to verify keys."


_CMD = re.compile(r"^\s*(?:show\s+|open\s+)?gemini\s+(settings|status|accounts|usage|health|reload|check|deep check|use|select)(?:\s+(?:slot\s+)?([1-3]))?\s*$", re.I)


class GeminiSettingsCommandHandler:
    """handle(query) -> bool, same pattern as other Aliena command handlers."""

    def __init__(self, settings: Optional[GeminiSettings] = None, speak: Optional[Callable[[str], None]] = None) -> None:
        self.settings = settings or GeminiSettings()
        self.speak = speak or (lambda m: None)

    def handle(self, query: str) -> bool:
        m = _CMD.match(query or "")
        if not m:
            return False
        cmd, slot = m.group(1).lower(), int(m.group(2)) if m.group(2) else None
        if cmd in ("settings", "status", "accounts", "usage", "health"):
            self.speak(self.settings.render_text())
        elif cmd == "reload":
            self.speak(self.settings.reload())
        elif cmd in ("check", "deep check"):
            self.speak(self.settings.check(slot, deep=cmd == "deep check"))
        else:
            self.speak(self.settings.use(slot) if slot else "Say which slot: gemini use 1, 2 or 3.")
        return True


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    s = GeminiSettings()
    if not argv or argv[0] == "status":
        print(s.render_text())
    elif argv[0] in ("check", "deep-check") and len(argv) <= 2:
        print(s.check(int(argv[1]) if len(argv) == 2 and argv[1] in "123" else None, deep=argv[0] == "deep-check"))
    else:
        print("usage: python -m jarvis.ai.gemini_settings [status | check [1-3] | deep-check [1-3]]")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
