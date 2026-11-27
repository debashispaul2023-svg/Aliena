"""Gemini multi-account configuration, health monitoring and bounded retry/cooldown.

Policy (enforced in code, covered by tests):
  * Up to three independently configured keys: GEMINI_API_KEY_1..3, read from the environment only.
  * Keys are never printed, logged, returned, persisted or included in errors (``Secret`` + sanitising).
  * The ACTIVE slot is chosen explicitly (GEMINI_ACTIVE_SLOT or the Settings command), never by failure.
    A rate limit, quota error, invalid key or outage on one slot NEVER causes another slot to be used:
    there is no key rotation, so quotas, restrictions and billing controls are not circumvented.
  * The model is fixed by configuration (GEMINI_MODEL, default unchanged); it is never switched automatically.
  * Transient failures (timeout, network, HTTP 429/5xx) get a small bounded retry, then a cooldown during which
    NO request is sent. Invalid/forbidden keys are not retried and block the slot until an explicit re-check.
  * "Verified" is reported only after a real successful API response. Configuration alone is "Configured".
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from jarvis.core.redaction import redact_secrets

log = logging.getLogger("jarvis.gemini")

SLOT_COUNT = 3
ENV_VARS = tuple(f"GEMINI_API_KEY_{i}" for i in range(1, SLOT_COUNT + 1))
LEGACY_ENV_VAR = "GEMINI_API_KEY"
API_HOST = "generativelanguage.googleapis.com"
API_BASE = f"https://{API_HOST}/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"  # unchanged from the existing integration
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KEY_RE = re.compile(r"^[A-Za-z0-9._\-]{20,200}$")
PLACEHOLDER_RE = re.compile(r"your|replace|changeme|example|placeholder|xxxx|insert|paste", re.I)
MAX_RETRIES_CAP = 3
MAX_WAIT_S = 20.0          # never sleep longer than this inside one request
MAX_COOLDOWN_S = 900.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TRANSIENT = frozenset({"rate_limited", "server_error", "network_error", "timeout"})
BLOCKING = frozenset({"invalid_key", "permission_denied", "model_not_found"})


class Secret:
    """Holds a key; every textual/serialised form is redacted. Use .reveal() only when building a request."""

    __slots__ = ("_v",)

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_v", value)

    def reveal(self) -> str:
        return self._v

    def __repr__(self) -> str:
        return "<redacted>"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("Secret cannot be pickled")

    def __setattr__(self, *_a):
        raise AttributeError("Secret is immutable")


@dataclass(frozen=True)
class SlotConfig:
    slot: int
    env_var: str
    secret: Optional[Secret]
    state: str                 # missing | malformed | configured
    problem: str = ""
    fingerprint: Optional[str] = None
    duplicate_of: Optional[int] = None

    @property
    def usable(self) -> bool:
        return self.state == "configured" and self.duplicate_of is None


def _normalise(raw: Optional[str]) -> str:
    v = (raw or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def load_slots(env: Optional[Mapping[str, str]] = None) -> list[SlotConfig]:
    import os
    env = os.environ if env is None else env
    out: list[SlotConfig] = []
    seen: dict[str, int] = {}
    for i, var in enumerate(ENV_VARS, start=1):
        v = _normalise(env.get(var))
        if not v:
            out.append(SlotConfig(i, var, None, "missing"))
            continue
        problem = ""
        if not KEY_RE.match(v):
            problem = "value has an invalid length or characters (whitespace, quotes, newlines and non-ASCII are not allowed)"
        elif PLACEHOLDER_RE.search(v):
            problem = "value looks like a placeholder, not a real key"
        if problem:
            out.append(SlotConfig(i, var, None, "malformed", problem))
            continue
        fp = hashlib.sha256(v.encode("ascii")).hexdigest()
        dup = seen.get(fp)
        seen.setdefault(fp, i)
        out.append(SlotConfig(i, var, Secret(v), "configured", "", fp, dup))
    return out


# ------------------------------------------------------------------ transport
@dataclass
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: Optional[bytes]
    timeout: float


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[HttpRequest], HttpResponse]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # never follow redirects: the key header must not leave the API host
        return None


def urllib_transport(req: HttpRequest) -> HttpResponse:
    parts = urllib.parse.urlsplit(req.url)
    if parts.scheme != "https" or parts.hostname != API_HOST or parts.username or parts.password or parts.query:
        raise ValueError("refusing to send credentials to a non-Gemini endpoint")
    opener = urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(req.url, data=req.body, method=req.method, headers=req.headers)
    try:
        with opener.open(request, timeout=req.timeout) as resp:
            return HttpResponse(resp.status, {k: v for k, v in resp.headers.items()}, resp.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES])
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_RESPONSE_BYTES)
        return HttpResponse(exc.code, {k: v for k, v in (exc.headers or {}).items()}, body)
    except (socket.timeout, TimeoutError):
        raise TimeoutError("request timed out") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise TimeoutError("request timed out") from None
        raise ConnectionError("network error") from None


# ------------------------------------------------------------------ classification
@dataclass
class Outcome:
    ok: bool
    category: str = ""
    message: str = ""
    retry_after: Optional[float] = None
    text: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    http_status: Optional[int] = None


def _retry_after(headers: Mapping[str, str], err: dict) -> Optional[float]:
    for k, v in headers.items():
        if k.lower() == "retry-after":
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                break
    for d in err.get("details", []) if isinstance(err, dict) else []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.match(r"^(\d+(?:\.\d+)?)s$", str(d.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    return None


def classify_http(status: int, headers: Mapping[str, str], body: bytes) -> Outcome:
    err: dict = {}
    try:
        data = json.loads(body.decode("utf-8", "replace")) if body else {}
        err = data.get("error", {}) if isinstance(data, dict) else {}
    except ValueError:
        pass
    msg = str(err.get("message", ""))[:300] if isinstance(err, dict) else ""
    st = str(err.get("status", "")) if isinstance(err, dict) else ""
    low = (msg + " " + body[:2000].decode("utf-8", "replace")).lower()
    ra = _retry_after(headers, err)
    base = dict(message=msg, retry_after=ra, http_status=status)
    if status == 401 or (status == 400 and ("api_key_invalid" in low or "api key not valid" in low or "api key expired" in low)):
        return Outcome(False, "invalid_key", **base)
    if status == 403 or (status == 400 and st == "FAILED_PRECONDITION"):
        return Outcome(False, "permission_denied", **base)
    if status == 404:
        return Outcome(False, "model_not_found", **base)
    if status == 429:
        return Outcome(False, "rate_limited", **base)
    if status in (500, 502, 503, 504):
        return Outcome(False, "server_error", **base)
    if status == 408:
        return Outcome(False, "timeout", **base)
    if status == 400:
        return Outcome(False, "bad_request", **base)
    return Outcome(False, "unknown_http", **base)


def parse_generate(body: bytes) -> Outcome:
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return Outcome(False, "empty_response", "response was not valid JSON")
    if not isinstance(data, dict):
        return Outcome(False, "empty_response", "unexpected response shape")
    um = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
    usage = {k: int(um[src]) for k, src in (("prompt_tokens", "promptTokenCount"), ("completion_tokens", "candidatesTokenCount"),
                                            ("total_tokens", "totalTokenCount")) if isinstance(um.get(src), int)}
    cands = data.get("candidates") if isinstance(data.get("candidates"), list) else []
    text = ""
    finish = ""
    if cands and isinstance(cands[0], dict):
        finish = str(cands[0].get("finishReason", ""))
        content = cands[0].get("content") if isinstance(cands[0].get("content"), dict) else {}
        text = "".join(p.get("text", "") for p in content.get("parts", []) if isinstance(p, dict) and isinstance(p.get("text"), str))
    if text:
        return Outcome(True, text=text, usage=usage, http_status=200)
    block = (data.get("promptFeedback") or {}).get("blockReason") if isinstance(data.get("promptFeedback"), dict) else None
    if block or finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
        return Outcome(False, "blocked_content", f"content blocked ({block or finish})", usage=usage, http_status=200)
    return Outcome(False, "empty_response", "model returned no text", usage=usage, http_status=200)


# ------------------------------------------------------------------ state
@dataclass
class SlotRuntime:
    status: str = "unverified"          # unverified | ok | <failure category> | missing | malformed | duplicate
    verified_at: Optional[float] = None  # last REAL successful response
    last_error_category: str = ""
    last_error_message: str = ""
    last_error_at: Optional[float] = None
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    blocked: bool = False
    requests: int = 0
    successes: int = 0
    retries: int = 0
    rate_limit_events: int = 0
    failures: dict[str, int] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})


@dataclass
class AccountResult:
    ok: bool
    text: str = ""
    slot: Optional[int] = None
    model: str = ""
    error: Optional[str] = None
    category: str = ""
    attempts: int = 0
    retries: int = 0
    cooldown_s: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    network_attempted: bool = False


_FRIENDLY = {
    "invalid_key": "API key rejected by Google (invalid or expired)",
    "permission_denied": "access denied for this key (permissions, region, leaked/disabled key or API not enabled)",
    "model_not_found": "model not found or not available to this key",
    "rate_limited": "rate limit / quota reached (HTTP 429)",
    "server_error": "Google service error (HTTP 5xx)",
    "network_error": "network error",
    "timeout": "request timed out",
    "bad_request": "request rejected as invalid (HTTP 400)",
    "unknown_http": "unexpected HTTP response",
    "empty_response": "model returned no text",
    "blocked_content": "content was blocked by Google's safety filters",
}


class GeminiAccountManager:
    def __init__(self, env: Optional[Mapping[str, str]] = None, *, transport: Optional[Transport] = None,
                 time_fn: Callable[[], float] = time.time, sleep_fn: Callable[[float], None] = time.sleep,
                 max_retries: Optional[int] = None, model: Optional[str] = None, timeout_s: Optional[float] = None) -> None:
        import os
        self._env_src = os.environ if env is None else env
        self.transport = transport or urllib_transport
        self._time, self._sleep = time_fn, sleep_fn
        self._lock = threading.RLock()
        self._explicit = (max_retries, model, timeout_s)
        self.notes: list[str] = []
        self._load()

    # ---- configuration
    def _load(self) -> None:
        env = self._env_src
        max_retries, model, timeout_s = self._explicit
        self.notes = []
        raw_model = _normalise(model if model is not None else env.get("GEMINI_MODEL"))
        if raw_model and MODEL_RE.match(raw_model):
            self.model = raw_model
        else:
            if raw_model:
                self.notes.append("GEMINI_MODEL is not a valid model name; using the default")
            self.model = DEFAULT_MODEL
        try:
            mr = int(max_retries if max_retries is not None else env.get("GEMINI_MAX_RETRIES", 2))
        except (TypeError, ValueError):
            mr = 2
        self.max_retries = max(0, min(mr, MAX_RETRIES_CAP))
        try:
            ts = float(timeout_s if timeout_s is not None else env.get("GEMINI_TIMEOUT_S", 30))
        except (TypeError, ValueError):
            ts = 30.0
        self.timeout_s = max(5.0, min(ts, 120.0))
        old = {c.slot: (c.fingerprint, getattr(self, "_rt", {}).get(c.slot)) for c in getattr(self, "configs", [])}
        self.configs = load_slots(env)
        self._rt: dict[int, SlotRuntime] = {}
        for c in self.configs:
            prev_fp, prev_rt = old.get(c.slot, (None, None))
            if prev_rt is not None and prev_fp == c.fingerprint and c.fingerprint is not None:
                self._rt[c.slot] = prev_rt          # same key: keep its counters/cooldown
            else:
                rt = SlotRuntime()
                rt.status = c.state if c.state != "configured" else ("duplicate" if c.duplicate_of else "unverified")
                self._rt[c.slot] = rt
        self._select_initial_active()

    def reload_from_env(self) -> None:
        """Re-read the environment (e.g. after fixing a key). Counters are kept only for unchanged keys."""
        with self._lock:
            self._load()

    def _select_initial_active(self) -> None:
        usable = [c.slot for c in self.configs if c.usable]
        wanted = _normalise(self._env_src.get("GEMINI_ACTIVE_SLOT"))
        self._active: Optional[int] = None
        if wanted:
            try:
                n = int(wanted)
            except ValueError:
                n = 0
            if n in usable:
                self._active = n
            else:
                self.notes.append("GEMINI_ACTIVE_SLOT does not point to a configured slot; using the first configured slot")
        if self._active is None and usable:
            self._active = usable[0]
        for c in self.configs:
            if c.duplicate_of:
                self.notes.append(f"slot {c.slot} holds the same key as slot {c.duplicate_of}; it is not treated as a separate account")
            if c.state == "malformed":
                self.notes.append(f"slot {c.slot} ({c.env_var}): {c.problem}")
        if self._env_src.get(LEGACY_ENV_VAR) and not usable:
            self.notes.append("legacy GEMINI_API_KEY is set; it is used by the original single-key client only when no slot key is configured")

    @property
    def any_configured(self) -> bool:
        return any(c.state != "missing" for c in self.configs)

    @property
    def active_slot(self) -> Optional[int]:
        return self._active

    def select_slot(self, n: int) -> tuple[bool, str]:
        """Explicit user choice of the active slot. Never called automatically."""
        with self._lock:
            c = next((c for c in self.configs if c.slot == n), None)
            if c is None:
                return False, "slot must be 1, 2 or 3"
            if c.state == "missing":
                return False, f"slot {n} has no key configured"
            if c.state == "malformed":
                return False, f"slot {n} key is malformed: fix {c.env_var}"
            if c.duplicate_of:
                return False, f"slot {n} holds the same key as slot {c.duplicate_of}"
            if self._rt[n].blocked:
                return False, f"slot {n} is blocked ({self._rt[n].last_error_category}); fix the key and run a check first"
            self._active = n
            log.info("active Gemini slot set to %s by explicit request", n)
            return True, f"active slot is now {n}"

    # ---- sanitising
    def _clean(self, text: str) -> str:
        t = str(text or "")
        for c in self.configs:
            if c.secret is not None:
                t = t.replace(c.secret.reveal(), "[REDACTED]")
        return " ".join(redact_secrets(t).split())[:200]

    # ---- status
    def _cooldown_remaining(self, n: int) -> float:
        return max(0.0, self._rt[n].cooldown_until - self._time())

    def available(self) -> bool:
        with self._lock:
            n = self._active
            return n is not None and not self._rt[n].blocked and self._cooldown_remaining(n) <= 0

    def last_error(self) -> Optional[str]:
        with self._lock:
            if self._active is None:
                return "no Gemini key configured (set GEMINI_API_KEY_1, _2 or _3)"
            rt = self._rt[self._active]
            return self._clean(rt.last_error_message) or None

    def slots(self) -> list[dict[str, Any]]:
        """Public, key-free view of every slot."""
        with self._lock:
            out = []
            for c in self.configs:
                rt = self._rt[c.slot]
                out.append({
                    "slot": c.slot, "env_var": c.env_var, "configured": c.state == "configured", "config_state": c.state,
                    "problem": c.problem, "duplicate_of": c.duplicate_of, "active": c.slot == self._active,
                    "status": rt.status, "verified": rt.verified_at is not None and rt.status == "ok",
                    "verified_at": rt.verified_at, "blocked": rt.blocked,
                    "cooldown_remaining_s": round(self._cooldown_remaining(c.slot), 1),
                    "last_error": rt.last_error_category or None, "last_error_message": self._clean(rt.last_error_message) or None,
                    "usage": {"requests": rt.requests, "successes": rt.successes, "retries": rt.retries,
                              "rate_limit_events": rt.rate_limit_events, "errors": dict(rt.failures), "tokens": dict(rt.tokens),
                              "quota_remaining": "not exposed by the Gemini API"},
                })
            return out

    def health(self) -> dict[str, Any]:
        s = self.slots()
        act = next((x for x in s if x["active"]), None)
        if act is None:
            overall = "not_configured"
        elif act["blocked"]:
            overall = "blocked"
        elif act["cooldown_remaining_s"] > 0:
            overall = "cooling_down"
        elif act["status"] == "ok":
            overall = "healthy"
        elif act["status"] == "unverified":
            overall = "unverified"
        else:
            overall = "degraded"
        return {"overall": overall, "active_slot": self._active, "model": self.model, "slots": s, "notes": list(self.notes)}

    # ---- request engine
    def _record_attempt(self, n: int, out: Outcome) -> None:
        rt = self._rt[n]
        rt.requests += 1
        if out.ok:
            rt.successes += 1
            for k, v in out.usage.items():
                rt.tokens[k] = rt.tokens.get(k, 0) + v
        else:
            rt.failures[out.category] = rt.failures.get(out.category, 0) + 1
            if out.category == "rate_limited":
                rt.rate_limit_events += 1

    def _http(self, n: int, method: str, path: str, body: Optional[dict], timeout: float) -> Outcome:
        key = self.configs[n - 1].secret.reveal()
        headers = {"x-goog-api-key": key, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = HttpRequest(method, f"{API_BASE}/{path}", headers, data, timeout)
        try:
            resp = self.transport(req)
        except TimeoutError:
            return Outcome(False, "timeout", "request timed out")
        except (ConnectionError, OSError):
            return Outcome(False, "network_error", "network error")
        except Exception as exc:  # transport bugs must not leak anything or crash the app
            return Outcome(False, "network_error", f"transport failure ({type(exc).__name__})")
        if resp.status == 200:
            return parse_generate(resp.body) if method == "POST" else Outcome(True, http_status=200)
        return classify_http(resp.status, resp.headers, resp.body)

    def _cooldown_for(self, category: str, retry_after: Optional[float], consecutive: int) -> float:
        base = 60.0 if category == "rate_limited" else 15.0
        cap = MAX_COOLDOWN_S if category == "rate_limited" else 300.0
        cd = base * (2 ** max(0, consecutive - 1))
        if retry_after:
            cd = max(cd, retry_after)
        return min(cd, cap)

    def _run(self, n: int, method: str, path: str, body: Optional[dict], timeout: Optional[float], retries_allowed: int) -> AccountResult:
        deadline = self._time() + timeout if timeout and timeout > 0 else None
        per_attempt = min(self.timeout_s, timeout) if timeout and timeout > 0 else self.timeout_s
        attempts = retries = 0
        while True:
            attempts += 1
            out = self._http(n, method, path, body, per_attempt)
            with self._lock:
                self._record_attempt(n, out)
                rt = self._rt[n]
                if out.ok:
                    rt.status, rt.verified_at = "ok", self._time()
                    rt.consecutive_failures, rt.cooldown_until, rt.blocked = 0, 0.0, False
                    rt.last_error_category = rt.last_error_message = ""
                    log.info("gemini slot %s: request ok", n)
                    return AccountResult(True, out.text, n, self.model, None, "", attempts, retries, 0.0, out.usage, True)
                rt.last_error_category, rt.last_error_at = out.category, self._time()
                rt.last_error_message = self._clean(out.message) or _FRIENDLY.get(out.category, out.category)
            if out.category not in TRANSIENT:
                with self._lock:
                    rt = self._rt[n]
                    rt.status = out.category
                    if out.category in BLOCKING:
                        rt.blocked = True
                        rt.consecutive_failures += 1
                log.warning("gemini slot %s: %s", n, out.category)
                return self._fail(n, out, attempts, retries, 0.0)
            # transient: bounded retry, then cooldown
            wait = out.retry_after if out.retry_after is not None else float(2 ** (attempts - 1))
            can_retry = (retries < retries_allowed and wait <= MAX_WAIT_S
                         and (deadline is None or self._time() + wait < deadline))
            if can_retry:
                with self._lock:
                    self._rt[n].retries += 1
                retries += 1
                self._sleep(wait)
                continue
            with self._lock:
                rt = self._rt[n]
                rt.consecutive_failures += 1
                cd = self._cooldown_for(out.category, out.retry_after, rt.consecutive_failures)
                rt.cooldown_until = self._time() + cd
                rt.status = out.category
            log.warning("gemini slot %s: %s after %s attempt(s); cooldown %.0fs", n, out.category, attempts, cd)
            return self._fail(n, out, attempts, retries, cd)

    def _fail(self, n: int, out: Outcome, attempts: int, retries: int, cooldown: float) -> AccountResult:
        text = _FRIENDLY.get(out.category, out.category)
        extra = f" after {retries} retr{'y' if retries == 1 else 'ies'}" if retries else ""
        cool = f"; cooling down {int(cooldown)}s" if cooldown else ""
        fix = f"; fix the key, reload, then run 'gemini check {n}'" if out.category in BLOCKING else ""
        # 'unavailable' keeps the router from stacking its own retries on top of ours
        msg = f"Gemini slot {n} unavailable: {text}{extra}{cool}{fix}" if out.category in TRANSIENT | BLOCKING else f"Gemini slot {n}: {text}"
        return AccountResult(False, "", n, self.model, msg, out.category, attempts, retries, cooldown, out.usage, True)

    # ---- public operations
    def generate(self, prompt: Any, *, timeout: Optional[float] = None, **options: Any) -> AccountResult:
        with self._lock:
            n = self._active
            if n is None:
                return AccountResult(False, error="Gemini unavailable: no API key configured (set GEMINI_API_KEY_1, _2 or _3)",
                                     category="missing")
            rt = self._rt[n]
            if rt.blocked:
                return AccountResult(False, slot=n, model=self.model, category=rt.last_error_category,
                                     error=f"Gemini slot {n} unavailable: {_FRIENDLY.get(rt.last_error_category, 'blocked')}; "
                                           f"fix the key, reload, then run 'gemini check {n}'")
            remaining = self._cooldown_remaining(n)
            if remaining > 0:
                return AccountResult(False, slot=n, model=self.model, category=rt.status, cooldown_s=remaining,
                                     error=f"Gemini slot {n} unavailable: cooling down {int(remaining) + 1}s after "
                                           f"{_FRIENDLY.get(rt.last_error_category, rt.status)}")
        body, problem = _build_body(prompt, options)
        if problem:
            return AccountResult(False, slot=n, model=self.model, category="bad_request", error=f"Gemini slot {n}: {problem}")
        return self._run(n, "POST", f"models/{self.model}:generateContent", body, timeout, self.max_retries)

    def check_slot(self, n: int, *, deep: bool = False) -> AccountResult:
        """REAL request to verify a slot (explicit user action). Shallow = GET the model (no tokens used);
        deep = tiny generateContent. One attempt only; never bypasses an active cooldown."""
        with self._lock:
            c = next((c for c in self.configs if c.slot == n), None)
            if c is None:
                return AccountResult(False, error="slot must be 1, 2 or 3", category="bad_request")
            if c.state != "configured":
                return AccountResult(False, slot=n, category=c.state,
                                     error=f"slot {n} is {c.state}" + (f": {c.problem}" if c.problem else f": set {c.env_var}"))
            remaining = self._cooldown_remaining(n)
            if remaining > 0:
                return AccountResult(False, slot=n, category="rate_limited", cooldown_s=remaining,
                                     error=f"slot {n} is cooling down for {int(remaining) + 1}s; no request sent")
        if deep:
            body = {"contents": [{"parts": [{"text": "Reply with the single word OK."}]}], "generationConfig": {"maxOutputTokens": 8}}
            return self._run(n, "POST", f"models/{self.model}:generateContent", body, self.timeout_s, 0)
        return self._run(n, "GET", f"models/{self.model}", None, self.timeout_s, 0)


_OPTION_MAP = {"temperature": ("temperature", float, 0.0, 2.0), "top_p": ("topP", float, 0.0, 1.0),
               "top_k": ("topK", int, 1, 1000), "max_output_tokens": ("maxOutputTokens", int, 1, 65536)}
MAX_PROMPT_CHARS = 500_000


def _build_body(prompt: Any, options: Mapping[str, Any]) -> tuple[Optional[dict], str]:
    parts: list[str]
    if isinstance(prompt, str):
        parts = [prompt]
    elif isinstance(prompt, (list, tuple)) and prompt and all(isinstance(p, str) for p in prompt):
        parts = list(prompt)
    else:
        return None, "unsupported prompt type (text only)"
    if not any(p.strip() for p in parts) or sum(len(p) for p in parts) > MAX_PROMPT_CHARS:
        return None, "prompt is empty or too large"
    cfg: dict[str, Any] = {}
    for k, v in options.items():
        spec = _OPTION_MAP.get(k)
        if spec is None:
            continue  # unknown options are ignored, never forwarded
        name, typ, lo, hi = spec
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            return None, f"option {k} out of range"
        cfg[name] = typ(v)
    body: dict[str, Any] = {"contents": [{"parts": [{"text": p} for p in parts]}]}
    if cfg:
        body["generationConfig"] = cfg
    return body, ""


# ------------------------------------------------------------------ shared instance
_shared: Optional[GeminiAccountManager] = None
_shared_lock = threading.Lock()


def shared_manager() -> GeminiAccountManager:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = GeminiAccountManager()
        return _shared


def reset_shared_manager() -> None:
    global _shared
    with _shared_lock:
        _shared = None


def slot_keys_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    import os
    env = os.environ if env is None else env
    return any(_normalise(env.get(v)) for v in ENV_VARS)
