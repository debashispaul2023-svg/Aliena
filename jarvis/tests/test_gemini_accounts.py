"""Gemini multi-account tests. All offline: a scripted fake transport and a fake clock; no real network, no real keys."""

import ast
import contextlib
import copy
import io
import json
import logging
import os
import pickle
import socket
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import jarvis.ai.gemini_accounts as ga
from jarvis.ai.gemini_accounts import (GeminiAccountManager, HttpRequest, HttpResponse, Secret, classify_http, load_slots,
                                       parse_generate, urllib_transport)
from jarvis.ai.gemini_settings import GeminiSettings, GeminiSettingsCommandHandler
from jarvis.ai.providers.deterministic import DeterministicProvider
from jarvis.ai.providers.gemini import GeminiProvider
from jarvis.ai.providers.gemini_multi import (AccountGeminiClient, GeminiMultiAccountProvider, build_account_client_if_configured,
                                              make_default_gemini_provider)
from jarvis.ai.router import ProviderRouter

K1 = "AIzaSyTESTKEY1-abcdefghijklmnopqrstuv"
K2 = "AIzaSyTESTKEY2-abcdefghijklmnopqrstuv"
K3 = "AIzaSyTESTKEY3-abcdefghijklmnopqrstuv"
ENV3 = {"GEMINI_API_KEY_1": K1, "GEMINI_API_KEY_2": K2, "GEMINI_API_KEY_3": K3}
OK_BODY = json.dumps({"candidates": [{"content": {"parts": [{"text": "hello"}]}, "finishReason": "STOP"}],
                      "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5}}).encode()


def err_body(code, status, message="x", reason=None, retry_delay=None):
    details = []
    if reason:
        details.append({"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason})
    if retry_delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay})
    return json.dumps({"error": {"code": code, "message": message, "status": status, "details": details}}).encode()


def R(status=200, body=OK_BODY, headers=None):
    return HttpResponse(status, headers or {}, body)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def advance(self, s):
        self.now += s


class Fake:
    """Scripted transport: each item is an HttpResponse, an exception instance, or a callable(req)."""

    def __init__(self, *script, default=None):
        self.script, self.default, self.requests = list(script), default, []

    def __call__(self, req: HttpRequest):
        self.requests.append(req)
        item = self.script.pop(0) if self.script else self.default
        if item is None:
            raise AssertionError("unexpected request")
        if callable(item) and not isinstance(item, HttpResponse):
            item = item(req)
        if isinstance(item, BaseException):
            raise item
        return item

    def keys_used(self):
        return [r.headers.get("x-goog-api-key") for r in self.requests]


def mk(env=None, transport=None, **kw):
    clock = Clock()
    m = GeminiAccountManager(env=ENV3 if env is None else env, transport=transport or Fake(default=R()),
                             time_fn=clock.time, sleep_fn=clock.sleep, **kw)
    return m, clock


class TestSecret(unittest.TestCase):
    def test_never_exposes_value(self):
        s = Secret(K1)
        for text in (repr(s), str(s), f"{s}", "%s" % s, "{}".format(s), repr([s]), repr({"k": s})):
            self.assertNotIn(K1, text)
        with self.assertRaises(TypeError):
            pickle.dumps(s)
        with self.assertRaises(AttributeError):
            s._v = "x"
        self.assertEqual(s.reveal(), K1)
        with self.assertRaises(TypeError):  # copying/serialising a Secret is refused outright
            copy.deepcopy(s)
        self.assertNotIn(K1, repr(load_slots(ENV3)))


class TestConfigLoading(unittest.TestCase):
    def test_no_keys(self):
        m, _ = mk(env={})
        self.assertEqual([s["config_state"] for s in m.slots()], ["missing"] * 3)
        self.assertIsNone(m.active_slot)
        self.assertFalse(m.available())
        self.assertFalse(m.any_configured)
        self.assertEqual(m.health()["overall"], "not_configured")

    def test_slots_are_independent(self):
        for present in ((1,), (2,), (3,), (1, 3), (2, 3)):
            env = {f"GEMINI_API_KEY_{i}": [K1, K2, K3][i - 1] for i in present}
            m, _ = mk(env=env)
            got = [s["configured"] for s in m.slots()]
            self.assertEqual(got, [i in present for i in (1, 2, 3)])
            self.assertEqual(m.active_slot, present[0])

    def test_whitespace_quotes_and_empty(self):
        m, _ = mk(env={"GEMINI_API_KEY_1": f'  "{K1}"  ', "GEMINI_API_KEY_2": "   ", "GEMINI_API_KEY_3": ""})
        self.assertEqual([s["config_state"] for s in m.slots()], ["configured", "missing", "missing"])
        self.assertEqual(m.configs[0].secret.reveal(), K1)

    def test_malformed_values(self):
        bad = {"nl": K1 + "\nX-Evil: 1", "space": "AIza with space abcdefghijklmnop", "short": "AIza123", "uni": "AIza" + "é" * 30,
               "long": "A" * 300, "placeholder": "YOUR_GEMINI_API_KEY_GOES_HERE", "crlf": K1[:20] + "\r\n" + K1[20:]}
        for label, value in bad.items():
            m, _ = mk(env={"GEMINI_API_KEY_1": value})
            s = m.slots()[0]
            self.assertEqual((s["config_state"], s["configured"]), ("malformed", False), label)
            self.assertFalse(m.available(), label)
            self.assertNotIn(value, json.dumps(m.health()) + GeminiSettings(m).render_text(), label)

    def test_duplicate_keys(self):
        m, _ = mk(env={"GEMINI_API_KEY_1": K1, "GEMINI_API_KEY_2": K1, "GEMINI_API_KEY_3": K3})
        s = m.slots()
        self.assertEqual((s[1]["duplicate_of"], s[1]["status"]), (1, "duplicate"))
        self.assertFalse(m.select_slot(2)[0])
        self.assertTrue(any("same key as slot 1" in n for n in m.notes))

    def test_active_slot_selection(self):
        self.assertEqual(mk(env={**ENV3, "GEMINI_ACTIVE_SLOT": "2"})[0].active_slot, 2)
        for bad in ("9", "abc", "0", "-1", ""):
            m, _ = mk(env={**ENV3, "GEMINI_ACTIVE_SLOT": bad})
            self.assertEqual(m.active_slot, 1, bad)
        m, _ = mk(env={"GEMINI_API_KEY_3": K3, "GEMINI_ACTIVE_SLOT": "1"})
        self.assertEqual(m.active_slot, 3)
        self.assertTrue(any("GEMINI_ACTIVE_SLOT" in n for n in m.notes))

    def test_model_retries_timeout_settings(self):
        m, _ = mk()
        self.assertEqual((m.model, m.max_retries, m.timeout_s), ("gemini-2.5-flash", 2, 30.0))
        m, _ = mk(env={**ENV3, "GEMINI_MODEL": "gemini-2.0-flash", "GEMINI_MAX_RETRIES": "99", "GEMINI_TIMEOUT_S": "1"})
        self.assertEqual((m.model, m.max_retries, m.timeout_s), ("gemini-2.0-flash", 3, 5.0))
        for bad in ("../x", "a b", "m;rm", "x" * 80):
            self.assertEqual(mk(env={**ENV3, "GEMINI_MODEL": bad})[0].model, "gemini-2.5-flash", bad)
        self.assertEqual(mk(env={**ENV3, "GEMINI_MAX_RETRIES": "-4"})[0].max_retries, 0)
        self.assertEqual(mk(env={**ENV3, "GEMINI_MAX_RETRIES": "abc"})[0].max_retries, 2)

    def test_legacy_key_is_only_a_note(self):
        m, _ = mk(env={"GEMINI_API_KEY": K1})
        self.assertEqual([s["configured"] for s in m.slots()], [False] * 3)
        self.assertFalse(m.any_configured)
        self.assertTrue(any("legacy GEMINI_API_KEY" in n for n in m.notes))

    def test_reads_process_environment_by_default(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY_2": K2}, clear=False):
            m = GeminiAccountManager(transport=Fake())
            self.assertEqual([s["configured"] for s in m.slots()][1], True)

    def test_reload_keeps_counters_only_for_unchanged_key(self):
        env = dict(ENV3)
        t = Fake(default=R())
        m, _ = mk(env=env, transport=t)
        m.generate("hi")
        env["GEMINI_API_KEY_2"] = "AIzaSyNEWKEY2-abcdefghijklmnopqrstuvw"
        m.reload_from_env()
        self.assertEqual(m.slots()[0]["usage"]["requests"], 1)
        self.assertEqual(m.slots()[0]["status"], "ok")
        self.assertEqual(m.slots()[1]["usage"]["requests"], 0)

    def test_no_dotenv_or_file_reads(self):
        src = Path(ga.__file__).read_text()
        for banned in ("dotenv", "read_text", "write_text", "os.environ[", "putenv", "json.dump(", "import pickle"):
            self.assertNotIn(banned, src)
        import re
        self.assertIsNone(re.search(r"(?<![\w.])open\(", src), "builtin open() (file access) must not be used")


class TestSecrecy(unittest.TestCase):
    def test_no_key_fragment_anywhere(self):
        server_leak = err_body(400, "INVALID_ARGUMENT", message=f"API key not valid. key={K1}", reason="API_KEY_INVALID")
        t = Fake(R(), HttpResponse(400, {}, server_leak), ValueError(f"boom {K2}"), R(503), R(503), R(503), default=R())
        m, clock = mk(transport=t)
        out = io.StringIO()
        with self.assertLogs(level="DEBUG") as logs, contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            logging.getLogger("jarvis.gemini").debug("start")
            results = [m.generate("a")]
            results.append(m.generate("b"))      # invalid key -> blocked (message echoes the key)
            m.select_slot(2) if False else None
            m._active = 2                        # white-box: exercise other slots too
            results.append(m.generate("c"))      # transport ValueError containing key 2
            results.append(m.generate("d"))      # 503 x3
            m._active = 3
            results.append(m.check_slot(3))
        blob = "\n".join([
            json.dumps(m.slots()), json.dumps(m.health()), GeminiSettings(m).render_text(), repr(m), repr(m.configs),
            str(m.last_error()), out.getvalue(), "\n".join(logs.output), *[repr(r) for r in results]])
        for key in (K1, K2, K3):
            for frag in (key, key[:10], key[-10:]):
                self.assertNotIn(frag, blob)
        self.assertEqual(out.getvalue(), "")  # nothing printed

    def test_key_only_in_header_over_https_to_gemini_host(self):
        t = Fake(default=R())
        m, _ = mk(transport=t)
        m.generate("x")
        m.check_slot(1)
        for r in t.requests:
            self.assertTrue(r.url.startswith("https://generativelanguage.googleapis.com/v1beta/models/"))
            self.assertNotIn(K1, r.url)
            self.assertNotIn("key=", r.url)
            self.assertEqual(r.headers["x-goog-api-key"], K1)
            self.assertNotIn(K1, (r.body or b"").decode())

    def test_source_has_no_prints(self):
        for mod in ("gemini_accounts.py", "providers/gemini_multi.py", "gemini_settings.py"):
            tree = ast.parse((Path(ga.__file__).parent / mod).read_text())
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print"]
            if mod == "gemini_settings.py":
                self.assertEqual(len(calls), 3)  # CLI main() only
            else:
                self.assertEqual(calls, [], mod)


class TestMissingKeys(unittest.TestCase):
    def test_generate_without_keys_makes_no_request(self):
        t = Fake()
        m, _ = mk(env={}, transport=t)
        r = m.generate("hi")
        self.assertEqual((r.ok, r.category, r.network_attempted), (False, "missing", False))
        self.assertIn("no API key configured", r.error)
        self.assertEqual(t.requests, [])

    def test_check_and_select_on_missing_or_malformed_slot(self):
        t = Fake()
        m, _ = mk(env={"GEMINI_API_KEY_1": K1, "GEMINI_API_KEY_3": "bad value"}, transport=t)
        r2, r3, r9 = m.check_slot(2), m.check_slot(3), m.check_slot(9)
        self.assertEqual((r2.category, r3.category, r9.category), ("missing", "malformed", "bad_request"))
        self.assertIn("GEMINI_API_KEY_2", r2.error)
        self.assertEqual(t.requests, [])
        self.assertFalse(m.select_slot(2)[0])
        self.assertFalse(m.select_slot(3)[0])
        self.assertFalse(m.select_slot(0)[0])

    def test_provider_and_client_degrade_gracefully(self):
        m, _ = mk(env={}, transport=Fake())
        p = GeminiMultiAccountProvider(m)
        resp = p.generate("hi")
        self.assertEqual((resp.success, resp.mode, resp.provider), (False, "OFFLINE", "gemini"))
        self.assertFalse(p.available())
        c = AccountGeminiClient(m)
        self.assertFalse(c.available)
        self.assertTrue(c.generate("hi").startswith("[AI unavailable]"))
        self.assertTrue(c.generate_content("hi").text.startswith("[AI unavailable]"))


class TestInvalidKeys(unittest.TestCase):
    def test_invalid_key_is_not_retried_not_rotated_and_blocks(self):
        t = Fake(HttpResponse(400, {}, err_body(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.", "API_KEY_INVALID")))
        m, clock = mk(transport=t)
        r = m.generate("hi")
        self.assertEqual((r.ok, r.category, r.attempts, r.retries), (False, "invalid_key", 1, 0))
        self.assertEqual(clock.sleeps, [])
        self.assertTrue(m.slots()[0]["blocked"])
        self.assertEqual(m.health()["overall"], "blocked")
        self.assertIn("unavailable", r.error)
        n = len(t.requests)
        for _ in range(5):                                  # blocked: no further network traffic at all
            self.assertFalse(m.generate("again").ok)
        self.assertEqual(len(t.requests), n)
        self.assertEqual(set(t.keys_used()), {K1})          # slots 2 and 3 were never tried
        self.assertEqual(m.active_slot, 1)
        self.assertFalse(m.select_slot(1)[0])

    def test_status_codes(self):
        cases = [(401, "UNAUTHENTICATED", "invalid_key"), (403, "PERMISSION_DENIED", "permission_denied"),
                 (404, "NOT_FOUND", "model_not_found"), (400, "FAILED_PRECONDITION", "permission_denied")]
        for code, status, cat in cases:
            t = Fake(HttpResponse(code, {}, err_body(code, status)))
            m, _ = mk(transport=t)
            r = m.generate("hi")
            self.assertEqual((r.category, r.attempts), (cat, 1), code)
            self.assertTrue(m.slots()[0]["blocked"], code)
            self.assertEqual(len(t.requests), 1)

    def test_generic_400_is_not_blocking(self):
        t = Fake(HttpResponse(400, {}, err_body(400, "INVALID_ARGUMENT", "bad field")), R())
        m, _ = mk(transport=t)
        r = m.generate("hi")
        self.assertEqual((r.category, r.attempts, m.slots()[0]["blocked"], m.slots()[0]["cooldown_remaining_s"]), ("bad_request", 1, False, 0.0))
        self.assertTrue(m.generate("hi").ok)

    def test_recovery_requires_explicit_fix_reload_and_real_check(self):
        env = dict(ENV3)
        t = Fake(HttpResponse(400, {}, err_body(400, "INVALID_ARGUMENT", "API key not valid", "API_KEY_INVALID")), default=R())
        m, _ = mk(env=env, transport=t)
        m.generate("hi")
        env["GEMINI_API_KEY_1"] = "AIzaSyFIXEDKEY-abcdefghijklmnopqrstuvwx"
        self.assertTrue(m.slots()[0]["blocked"])             # nothing changes until reload
        m.reload_from_env()
        self.assertFalse(m.slots()[0]["blocked"])
        self.assertFalse(m.slots()[0]["verified"])           # still not verified until a real success
        self.assertTrue(m.check_slot(1).ok)
        self.assertTrue(m.slots()[0]["verified"])

    def test_check_on_blocked_slot_is_a_single_attempt(self):
        t = Fake(HttpResponse(403, {}, err_body(403, "PERMISSION_DENIED")), HttpResponse(403, {}, err_body(403, "PERMISSION_DENIED")))
        m, _ = mk(transport=t)
        m.generate("hi")
        r = m.check_slot(1)
        self.assertEqual((r.ok, r.attempts), (False, 1))


class TestTimeoutsAndNetwork(unittest.TestCase):
    def test_timeout_is_bounded_then_cooldown(self):
        t = Fake(default=TimeoutError("t"))
        m, clock = mk(transport=t)
        r = m.generate("hi")
        self.assertEqual((r.ok, r.category, r.attempts, r.retries), (False, "timeout", 3, 2))
        self.assertEqual(clock.sleeps, [1.0, 2.0])
        self.assertEqual(r.cooldown_s, 15.0)
        self.assertTrue(r.network_attempted)
        self.assertFalse(m.available())
        self.assertIn("unavailable", r.error)
        calls = len(t.requests)
        r2 = m.generate("again")                             # cooling down: nothing is sent
        self.assertEqual((r2.ok, r2.network_attempted, len(t.requests)), (False, False, calls))
        self.assertGreater(r2.cooldown_s, 0)
        self.assertEqual(set(t.keys_used()), {K1})

    def test_cooldown_expiry_then_escalation_and_cap(self):
        t = Fake(default=ConnectionError("down"))
        m, clock = mk(transport=t)
        seen = []
        for _ in range(8):
            r = m.generate("x")
            seen.append(r.cooldown_s)
            clock.advance(r.cooldown_s + 0.1)
            self.assertTrue(m.available())
        self.assertEqual(seen, [15.0, 30.0, 60.0, 120.0, 240.0, 300.0, 300.0, 300.0])

    def test_recovers_after_cooldown_and_resets_counters(self):
        t = Fake(*([TimeoutError()] * 3), default=R())
        m, clock = mk(transport=t)
        m.generate("x")
        clock.advance(16)
        r = m.generate("x")
        self.assertTrue(r.ok)
        s = m.slots()[0]
        self.assertEqual((s["status"], s["cooldown_remaining_s"], s["verified"]), ("ok", 0.0, True))
        self.assertEqual(m.health()["overall"], "healthy")

    def test_timeout_then_success_uses_one_retry(self):
        t = Fake(TimeoutError(), R())
        m, clock = mk(transport=t)
        r = m.generate("x")
        self.assertEqual((r.ok, r.attempts, r.retries, clock.sleeps), (True, 2, 1, [1.0]))
        self.assertEqual(m.slots()[0]["usage"]["retries"], 1)

    def test_total_deadline_stops_retries(self):
        t = Fake(default=TimeoutError())
        m, clock = mk(transport=t)
        r = m.generate("x", timeout=1.5)
        self.assertEqual((r.attempts, r.retries), (2, 1))   # waits of 1s then 2s would exceed the 1.5s budget

    def test_unexpected_transport_exception_is_contained_and_not_leaked(self):
        m, _ = mk(transport=Fake(default=ValueError(f"explode {K1}")))
        r = m.generate("x")
        self.assertEqual(r.category, "network_error")
        self.assertNotIn(K1, repr(r) + json.dumps(m.slots()))

    def test_retries_can_be_disabled(self):
        t = Fake(default=TimeoutError())
        m, clock = mk(transport=t, max_retries=0)
        self.assertEqual(m.generate("x").attempts, 1)
        self.assertEqual(clock.sleeps, [])

    def test_real_transport_mapping(self):
        req = HttpRequest("GET", "https://generativelanguage.googleapis.com/v1beta/models/m", {"x-goog-api-key": K1}, None, 5)
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=socket.timeout()):
            with self.assertRaises(TimeoutError):
                urllib_transport(req)
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.URLError(socket.timeout())):
            with self.assertRaises(TimeoutError):
                urllib_transport(req)
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(ConnectionError) as cm:
                urllib_transport(req)
            self.assertNotIn(K1, str(cm.exception))
        http_err = urllib.error.HTTPError(req.url, 429, "x", {"Retry-After": "7"}, io.BytesIO(b'{"error":{}}'))
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=http_err):
            resp = urllib_transport(req)
            self.assertEqual((resp.status, resp.headers.get("Retry-After")), (429, "7"))

    def test_real_transport_refuses_foreign_hosts_and_never_follows_redirects(self):
        for url in ("http://generativelanguage.googleapis.com/v1beta/m", "https://evil.example.com/v1beta/m",
                    "https://generativelanguage.googleapis.com.evil.com/x", "https://user:pw@generativelanguage.googleapis.com/x",
                    f"https://generativelanguage.googleapis.com/v1beta/m?key={K1}"):
            with mock.patch("urllib.request.OpenerDirector.open") as op:
                with self.assertRaises(ValueError):
                    urllib_transport(HttpRequest("GET", url, {"x-goog-api-key": K1}, None, 5))
                op.assert_not_called()
        self.assertIsNone(ga._NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example.com"))


class TestRateLimits(unittest.TestCase):
    def rl(self, retry_after=None, delay=None):
        return HttpResponse(429, {"Retry-After": str(retry_after)} if retry_after is not None else {},
                            err_body(429, "RESOURCE_EXHAUSTED", "quota", retry_delay=delay))

    def test_retry_after_honoured_bounded_then_cooldown(self):
        t = Fake(default=self.rl(5))
        m, clock = mk(transport=t)
        r = m.generate("x")
        self.assertEqual((r.category, r.attempts, r.retries, clock.sleeps), ("rate_limited", 3, 2, [5.0, 5.0]))
        self.assertEqual(r.cooldown_s, 60.0)
        self.assertEqual(m.slots()[0]["usage"]["rate_limit_events"], 3)
        self.assertIn("rate limit", r.error)

    def test_long_retry_after_means_no_waiting_just_cooldown(self):
        t = Fake(default=self.rl(120))
        m, clock = mk(transport=t)
        r = m.generate("x")
        self.assertEqual((r.attempts, clock.sleeps, r.cooldown_s), (1, [], 120.0))

    def test_retry_delay_from_body(self):
        t = Fake(self.rl(delay="3s"), R())
        m, clock = mk(transport=t)
        self.assertTrue(m.generate("x").ok)
        self.assertEqual(clock.sleeps, [3.0])

    def test_cooldown_blocks_all_requests_then_expires(self):
        t = Fake(default=self.rl(1))
        m, clock = mk(transport=t)
        m.generate("x")
        n = len(t.requests)
        for _ in range(20):
            r = m.generate("x")
            self.assertEqual((r.ok, r.network_attempted), (False, False))
        self.assertFalse(m.check_slot(1).ok)
        self.assertEqual(len(t.requests), n)                 # not a single request during the cooldown
        self.assertEqual(m.health()["overall"], "cooling_down")
        clock.advance(61)
        t.default = R()
        self.assertTrue(m.generate("x").ok)

    def test_escalation_capped_at_15_minutes(self):
        t = Fake(default=self.rl(1))
        m, clock = mk(transport=t)
        cds = []
        for _ in range(7):
            r = m.generate("x")
            cds.append(r.cooldown_s)
            clock.advance(r.cooldown_s + 1)
        self.assertEqual(cds, [60.0, 120.0, 240.0, 480.0, 900.0, 900.0, 900.0])

    def test_rate_limit_never_rotates_to_another_account(self):
        t = Fake(default=self.rl(1))
        m, clock = mk(transport=t)                           # all three slots configured
        for _ in range(40):
            m.generate("x")
            clock.advance(30)
        self.assertEqual(set(t.keys_used()), {K1})
        self.assertEqual(m.active_slot, 1)
        for s in m.slots()[1:]:
            self.assertEqual(s["usage"]["requests"], 0)
        self.assertEqual(m.slots()[0]["usage"]["requests"], len(t.requests))

    def test_requests_are_spaced_by_retries_and_cooldown_only(self):
        t = Fake(default=self.rl(1))
        m, clock = mk(transport=t)
        start = clock.now
        for _ in range(100):
            m.generate("x")
        self.assertLessEqual(len(t.requests), 3)             # 100 calls inside one cooldown window => at most the first 3 attempts
        self.assertEqual(clock.now - start, 2.0)

    def test_server_errors_transient(self):
        t = Fake(R(503), R(200))
        m, _ = mk(transport=t)
        self.assertTrue(m.generate("x").ok)
        t2 = Fake(default=R(500))
        m2, _ = mk(transport=t2)
        r = m2.generate("x")
        self.assertEqual((r.category, r.attempts, r.cooldown_s), ("server_error", 3, 15.0))


class TestHealthAndUsage(unittest.TestCase):
    def test_configured_is_not_verified(self):
        m, _ = mk(transport=Fake())
        s = m.slots()[0]
        self.assertEqual((s["configured"], s["status"], s["verified"], s["verified_at"]), (True, "unverified", False, None))
        self.assertEqual(m.health()["overall"], "unverified")
        text = GeminiSettings(m).render_text().lower()
        self.assertIn("not verified yet", text)
        self.assertNotIn("connected", text)

    def test_failed_check_does_not_verify(self):
        for resp in (TimeoutError(), R(429), R(403, err_body(403, "PERMISSION_DENIED")), R(200, b"not json")):
            m, _ = mk(transport=Fake(default=resp))
            r = m.check_slot(1)
            self.assertEqual(m.slots()[0]["verified"], r.ok)
        m, _ = mk(transport=Fake(default=TimeoutError()))
        self.assertFalse(m.check_slot(1).ok)
        self.assertFalse(m.slots()[0]["verified"])
        self.assertIn("NOT verified", GeminiSettings(m).check(1))

    def test_check_success_is_a_real_request_shallow_and_deep(self):
        t = Fake(default=R())
        m, clock = mk(transport=t)
        self.assertTrue(m.check_slot(2).ok)
        self.assertEqual((t.requests[0].method, t.requests[0].url.endswith("/models/gemini-2.5-flash")), ("GET", True))
        self.assertTrue(m.check_slot(2, deep=True).ok)
        self.assertEqual(t.requests[1].method, "POST")
        self.assertEqual(json.loads(t.requests[1].body)["generationConfig"], {"maxOutputTokens": 8})
        s = m.slots()[1]
        self.assertTrue(s["verified"] and s["verified_at"] == clock.now)
        self.assertFalse(m.slots()[0]["verified"])           # other slots unaffected
        self.assertEqual(m.slots()[1]["usage"]["requests"], 2)

    def test_empty_or_blocked_response_is_not_a_success(self):
        for body, cat in ((json.dumps({"candidates": []}).encode(), "empty_response"),
                          (json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode(), "blocked_content"),
                          (json.dumps({"candidates": [{"finishReason": "SAFETY"}]}).encode(), "blocked_content"),
                          (b"<html>", "empty_response")):
            m, _ = mk(transport=Fake(R(200, body)))
            r = m.generate("x")
            self.assertEqual((r.ok, r.category), (False, cat))
            self.assertFalse(m.slots()[0]["verified"])
            self.assertEqual(m.slots()[0]["cooldown_remaining_s"], 0.0)

    def test_usage_tokens_and_counters(self):
        m, _ = mk(transport=Fake(R(), R(), R(503), R(503), R(503)))
        m.generate("a")
        m.generate("b")
        m.generate("c")
        u = m.slots()[0]["usage"]
        self.assertEqual((u["requests"], u["successes"], u["tokens"]["total_tokens"], u["tokens"]["prompt_tokens"]), (5, 2, 10, 6))
        self.assertEqual((u["errors"], u["retries"]), ({"server_error": 3}, 2))
        self.assertEqual(u["quota_remaining"], "not exposed by the Gemini API")
        self.assertEqual(m.health()["overall"], "cooling_down")

    def test_per_slot_isolation(self):
        t = Fake(default=R())
        m, _ = mk(transport=t)
        m.generate("a")
        self.assertEqual(m.select_slot(3), (True, "active slot is now 3"))
        m.generate("b")
        self.assertEqual(t.keys_used(), [K1, K3])
        self.assertEqual([s["usage"]["requests"] for s in m.slots()], [1, 0, 1])

    def test_parse_and_classify_units(self):
        self.assertEqual(parse_generate(OK_BODY).usage["total_tokens"], 5)
        self.assertEqual(classify_http(429, {"retry-after": "9"}, b"{}").retry_after, 9.0)
        self.assertEqual(classify_http(429, {"Retry-After": "soon"}, b"{}").retry_after, None)
        self.assertEqual(classify_http(418, {}, b"").category, "unknown_http")
        self.assertEqual(classify_http(408, {}, b"").category, "timeout")


class TestRequestBuilding(unittest.TestCase):
    def test_options_prompt_and_model_are_validated(self):
        t = Fake(default=R())
        m, _ = mk(transport=t)
        m.generate(["part one", "part two"], temperature=0.3, max_output_tokens=50, top_p=0.9, top_k=5, evil="x", timeout=None)
        body = json.loads(t.requests[0].body)
        self.assertEqual(body["generationConfig"], {"temperature": 0.3, "maxOutputTokens": 50, "topP": 0.9, "topK": 5})
        self.assertEqual(len(body["contents"][0]["parts"]), 2)
        self.assertNotIn("evil", json.dumps(body))
        n = len(t.requests)
        for bad in (dict(prompt=""), dict(prompt="  "), dict(prompt=None), dict(prompt=b"x"), dict(prompt=[1, 2]),
                    dict(prompt="x" * 600_000), dict(prompt="x", temperature=99), dict(prompt="x", top_k=True)):
            p = bad.pop("prompt")
            r = m.generate(p, **bad)
            self.assertEqual((r.ok, r.category, r.network_attempted), (False, "bad_request", False), str(bad))
        self.assertEqual(len(t.requests), n)

    def test_model_is_fixed_across_failures(self):
        t = Fake(R(429), R(503), TimeoutError(), default=R())
        m, clock = mk(transport=t, model="gemini-2.0-flash")
        for _ in range(6):
            m.generate("x")
            clock.advance(2000)
        urls = {r.url for r in t.requests}
        self.assertEqual(urls, {"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"})

    def test_active_slot_only_changes_via_explicit_select(self):
        tree = ast.parse(Path(ga.__file__).read_text())
        writers = set()
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "_active" for t in n.targets):
                        writers.add(fn.name)
        self.assertEqual(writers, {"_select_initial_active", "select_slot"})
        src = Path(ga.__file__).read_text().lower()
        for banned in ("failover", "next_key", "fallback_model", "gemini-pro", "billing_enabled", "paid"):
            self.assertNotIn(banned, src)


class TestRouterIntegration(unittest.TestCase):
    def router(self, transport, env=ENV3):
        m, clock = mk(env=env, transport=transport)
        r = ProviderRouter(providers={"gemini": GeminiMultiAccountProvider(m), "deterministic": DeterministicProvider()},
                           preferred="gemini", fallback=["deterministic"], max_retries=2)
        return r, m, clock

    def test_success_path_is_live(self):
        r, m, _ = self.router(Fake(default=R()))
        res = r.generate("hello")
        self.assertEqual((res.selected_provider, res.response.mode, res.response.success, res.fallback_used), ("gemini", "LIVE", True, False))
        self.assertEqual((res.response.text, res.response.metadata["slot"], res.response.usage["total_tokens"]), ("hello", 1, 5))

    def test_rate_limit_falls_back_to_offline_deterministic_not_another_key(self):
        t = Fake(default=HttpResponse(429, {"Retry-After": "1"}, err_body(429, "RESOURCE_EXHAUSTED")))
        r, m, _ = self.router(t)
        res = r.generate("hello")
        self.assertEqual((res.selected_provider, res.fallback_used), ("deterministic", True))
        self.assertIn(res.response.mode, ("OFFLINE", "MOCKED"))
        self.assertEqual(len(t.requests), 3)                 # 1 + 2 bounded retries; the router did NOT multiply them
        self.assertEqual(set(t.keys_used()), {K1})
        res2 = r.generate("again")
        self.assertEqual(len(t.requests), 3)                 # cooling down: no more traffic
        self.assertEqual(res2.selected_provider, "deterministic")

    def test_invalid_key_falls_back_offline_without_hammering(self):
        t = Fake(default=HttpResponse(400, {}, err_body(400, "INVALID_ARGUMENT", "API key not valid", "API_KEY_INVALID")))
        r, m, _ = self.router(t)
        for _ in range(4):
            r.generate("x")
        self.assertEqual(len(t.requests), 1)
        self.assertEqual(set(t.keys_used()), {K1})

    def test_missing_keys_reported_offline(self):
        r, m, _ = self.router(Fake(), env={})
        res = r.generate("hello")
        self.assertEqual(res.selected_provider, "deterministic")
        self.assertEqual(res.original_error is not None, True)

    def test_default_router_backward_compatible(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        with mock.patch.dict(os.environ, clean, clear=True):
            ga.reset_shared_manager()
            self.assertIsInstance(ProviderRouter().get("gemini"), GeminiProvider)           # original provider, unchanged
            self.assertIsInstance(make_default_gemini_provider(), GeminiProvider)
            self.assertIsNone(build_account_client_if_configured())
        with mock.patch.dict(os.environ, {**clean, "GEMINI_API_KEY": K1}, clear=True):
            ga.reset_shared_manager()
            self.assertIsInstance(ProviderRouter().get("gemini"), GeminiProvider)           # legacy single key path
        with mock.patch.dict(os.environ, {**clean, "GEMINI_API_KEY_2": K2}, clear=True):
            ga.reset_shared_manager()
            p = ProviderRouter().get("gemini")
            self.assertIsInstance(p, GeminiMultiAccountProvider)
            self.assertEqual((p.name, p.mode, p.model), ("gemini", "LIVE", "gemini-2.5-flash"))
            self.assertIsInstance(build_account_client_if_configured(), AccountGeminiClient)
        ga.reset_shared_manager()

    def test_original_client_and_provider_untouched(self):
        from jarvis.ai.client import GeminiClient
        c = GeminiClient(api_key=None) if "GEMINI_API_KEY" not in os.environ else None
        if c is not None:
            self.assertFalse(c.available)
            self.assertTrue(c.generate("x").startswith("[AI unavailable]"))
        p = GeminiProvider(api_key=None)
        self.assertIn(p.name, ("gemini",))
        self.assertEqual(Path(ga.__file__).parents[0].joinpath("client.py").read_text().count("GEMINI_API_KEY"), 3)

    def test_account_client_contract(self):
        t = Fake(R(), HttpResponse(400, {}, err_body(400, "INVALID_ARGUMENT", "API key not valid", "API_KEY_INVALID")))
        m, _ = mk(transport=t)
        c = AccountGeminiClient(m)
        self.assertEqual((c.generate("hi"), c.generate_content("hi").text.startswith("[AI error]")), ("hello", True))
        self.assertTrue(c.generate("hi").startswith("[AI unavailable]"))
        self.assertFalse(hasattr(c, "api_key"))
        self.assertEqual(c.model_name, "gemini-2.5-flash")


class TestSettingsUI(unittest.TestCase):
    def test_slot_lines_configured_or_missing(self):
        m, _ = mk(env={"GEMINI_API_KEY_1": K1, "GEMINI_API_KEY_3": K3}, transport=Fake())
        lines = GeminiSettings(m).render_text().splitlines()
        self.assertEqual(lines[:3], ["Account slot 1: Configured (active)", "Account slot 2: Missing", "Account slot 3: Configured"])
        self.assertEqual(GeminiSettings(m).render_text(detailed=False).splitlines()[1], "Account slot 2: Missing")
        self.assertTrue(all(K in "" or K not in GeminiSettings(m).render_text() for K in (K1, K3)))
        self.assertEqual([r["state"] for r in GeminiSettings(m).rows()], ["Configured", "Missing", "Configured"])

    def test_view_only_commands_never_touch_the_network(self):
        t = Fake()
        m, _ = mk(transport=t)
        said = []
        h = GeminiSettingsCommandHandler(GeminiSettings(m), said.append)
        for q in ("gemini settings", "Show Gemini status", "gemini accounts", "gemini usage", "gemini health", "gemini reload"):
            self.assertTrue(h.handle(q), q)
        self.assertEqual(t.requests, [])
        self.assertIn("Account slot 2: Configured", said[0])

    def test_check_use_commands(self):
        t = Fake(default=R())
        m, _ = mk(transport=t)
        said = []
        h = GeminiSettingsCommandHandler(GeminiSettings(m), said.append)
        h.handle("gemini check 2")
        self.assertIn("Slot 2: connection verified by a real model lookup request", said[-1])
        self.assertEqual(len(t.requests), 1)
        h.handle("gemini deep check")
        self.assertIn("real generation request", said[-1])
        self.assertEqual(t.keys_used(), [K2, K1])
        h.handle("gemini use 3")
        self.assertEqual(said[-1], "active slot is now 3")
        h.handle("gemini use")
        self.assertIn("Say which slot", said[-1])
        h2, t2 = GeminiSettingsCommandHandler(GeminiSettings(mk(env={})[0]), said.append), None
        h2.handle("gemini check 1")
        self.assertIn("NOT verified", said[-1])
        h2.handle("gemini use 2")
        self.assertIn("no key configured", said[-1])

    def test_does_not_hijack_other_text(self):
        h = GeminiSettingsCommandHandler(GeminiSettings(mk(transport=Fake())[0]))
        for q in ("gemini", "tell me about gemini", "gemini is great", "what is gemini status of my order", "gemini check 7", "gemini use 4", "", None):
            self.assertFalse(h.handle(q), q)

    def test_cooldown_and_block_are_visible_in_settings(self):
        t = Fake(default=HttpResponse(429, {"Retry-After": "1"}, err_body(429, "RESOURCE_EXHAUSTED")))
        m, _ = mk(transport=t)
        m.generate("x")
        text = GeminiSettings(m).render_text()
        self.assertIn("rate limited; cooling down", text)
        self.assertIn("no requests sent", text)
        self.assertIn("rate-limit events 3", text)
        self.assertIn("Quota remaining: not exposed", text)
        m2, _ = mk(transport=Fake(HttpResponse(401, {}, err_body(401, "UNAUTHENTICATED"))))
        m2.generate("x")
        self.assertIn("blocked until the key is fixed", GeminiSettings(m2).render_text())

    def test_cli(self):
        ga.reset_shared_manager()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY_1": K1}, clear=False):
            ga.reset_shared_manager()
            out = io.StringIO()
            from jarvis.ai import gemini_settings
            with contextlib.redirect_stdout(out):
                self.assertEqual(gemini_settings.main(["status"]), 0)
            self.assertIn("Account slot 1: Configured", out.getvalue())
            self.assertNotIn(K1, out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gemini_settings.main(["bogus"]), 2)
        ga.reset_shared_manager()


class TestAppHooks(unittest.TestCase):
    def test_main_hooks_present_ordered_and_failsafe(self):
        src = (Path(ga.__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
        ast.parse(src)
        self.assertLess(src.index("ai_client = GeminiClient()"), src.index("build_account_client_if_configured()"))
        self.assertLess(src.index("resource_handler.handle(query)"), src.index("gemini_settings_handler.handle(query)"))
        self.assertLess(src.index("gemini_settings_handler.handle(query)"), src.index("creator_handler.handle(query)"))
        self.assertIn("if gemini_settings_handler is not None:", src)
        self.assertIn("Gemini multi-account init skipped", src)
        self.assertEqual(src.count("ai_client = GeminiClient()"), 1)

    def test_env_example_and_gitignore(self):
        root = Path(ga.__file__).parents[2]
        example = (root / ".env.example").read_text()
        for v in ("GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
            self.assertRegex(example, rf"(?m)^{v}=$")
        self.assertNotRegex(example, r"AIza[0-9A-Za-z_-]{20,}")
        for original in ("GITHUB_PERSONAL_ACCESS_TOKEN=", "POSTGRES_URL=", "JARVIS_FS_ROOT="):  # pre-existing entries preserved
            self.assertRegex(example, rf"(?m)^{original}$")
        gi = (root / ".gitignore").read_text().splitlines()
        self.assertIn(".env", gi)
        self.assertIn(".env.*", gi)
        self.assertIn("!.env.example", gi)


if __name__ == "__main__":
    unittest.main()
