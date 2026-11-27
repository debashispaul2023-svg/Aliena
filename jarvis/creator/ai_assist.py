"""AIAssist: advisory notes through the existing AI Provider Router, under a strict cost/safety policy.

* Default provider is the offline deterministic one; fallback is disabled.
* A live/paid provider is used ONLY if explicitly listed in approved_live_providers by the user.
* Output is advisory text: never executed, never written into project files, secrets redacted, mode labelled.
* Failures degrade to mode UNAVAILABLE; generation does not depend on this component."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from jarvis.core.redaction import redact_secrets

OFFLINE_PROVIDER = "deterministic"


class AIAssist:
    def __init__(self, router: Any = None, approved_live_providers: Iterable[str] = ()) -> None:
        self.router = router
        self.approved = frozenset(approved_live_providers)

    def advise(self, request: str, summary: str, provider: Optional[str] = None) -> dict[str, Any]:
        provider = provider or OFFLINE_PROVIDER
        if provider != OFFLINE_PROVIDER and provider not in self.approved:
            return {"mode": "DENIED", "provider": provider, "text": "",
                    "note": "live provider requires explicit user approval; no fallback to paid services", "live": False}
        if self.router is None:
            return {"mode": "UNAVAILABLE", "provider": provider, "text": "", "note": "no provider router configured", "live": False}
        prompt = redact_secrets(f"Review this project request and list risks or missing details in 3 bullets.\nRequest: {request[:500]}\nPlan: {summary[:500]}")
        try:
            res = self.router.generate(prompt, provider=provider, allow_fallback=False, timeout=20)
            resp = res.response
        except Exception as exc:
            return {"mode": "UNAVAILABLE", "provider": provider, "text": "", "note": f"router error: {type(exc).__name__}", "live": False}
        if not getattr(resp, "success", False):
            return {"mode": "UNAVAILABLE", "provider": provider, "text": "", "note": redact_secrets(str(getattr(resp, "error", ""))[:120]), "live": False}
        mode = str(getattr(resp, "mode", "OFFLINE")).upper()
        return {"mode": mode, "provider": getattr(res, "selected_provider", provider), "text": redact_secrets(str(resp.text))[:1000],
                "live": mode == "LIVE", "note": "advisory only; generation is deterministic and does not use this text"}
