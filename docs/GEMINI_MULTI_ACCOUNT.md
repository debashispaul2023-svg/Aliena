# Gemini multi-account configuration

Aliena can hold up to **three independently configured Gemini API keys** (slots 1-3) and shows which are
configured, whether they have been *verified by a real request*, and per-key usage and errors.

**What it does not do:** it never rotates keys to get around quotas, rate limits, account restrictions or billing
controls; it never switches model; it never switches to a paid model or a billing-enabled account.
You choose the active slot; failures never change it.

## Setup

1. Create one API key per account at https://aistudio.google.com/apikey (use only keys you are entitled to use).
2. Put them in the **process environment** (Aliena does not read `.env` files by itself; export them or use your launcher):

   | Variable | Meaning |
   |---|---|
   | `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3` | one key per slot; leave empty/unset = Missing |
   | `GEMINI_ACTIVE_SLOT` (optional) | 1-3. Default: lowest configured slot |
   | `GEMINI_MODEL` (optional) | default `gemini-2.5-flash` (unchanged). Fixed for the session |
   | `GEMINI_MAX_RETRIES` (optional) | 0-3, default 2: retries on the **same** key for timeouts/429/5xx |
   | `GEMINI_TIMEOUT_S` (optional) | 5-120, default 30, per request |

   * Linux/macOS: `export GEMINI_API_KEY_1="..."` (a `.env.example` template is provided; `.env` is git-ignored).
   * Windows PowerShell: `$env:GEMINI_API_KEY_1="..."` (current session) or `setx GEMINI_API_KEY_1 "..."` then reopen the terminal.
3. Start Aliena. If none of the three variables is set, the original single-key integration (`GEMINI_API_KEY`) runs exactly as before.

## Settings interface

Type in Aliena (or run `python -m jarvis.ai.gemini_settings`):

| Command | Effect |
|---|---|
| `gemini settings` / `status` / `usage` | show the slot table (no network) |
| `gemini check [1-3]` | **real** request (model lookup, no tokens) to verify the key |
| `gemini deep check [1-3]` | tiny real generation request (uses a few tokens) |
| `gemini use 1-3` | explicitly choose the active slot |
| `gemini reload` | re-read the environment (after fixing a key) |

Example:

```
Account slot 1: Configured (active)
Account slot 2: Missing
Account slot 3: Configured
Model: gemini-2.5-flash (fixed; never switched automatically)
- slot 1: verified by a real successful request at 14:03:11
- slot 3: not verified yet (no successful request so far)
```

"Configured" only means a well-formed key is present. **"Verified" appears only after a real successful API response**
(a check or a normal request). Keys, or any part of them, are never displayed, logged or stored.

## Failure handling

| Situation | Behaviour |
|---|---|
| Timeout, network error, HTTP 5xx | up to `GEMINI_MAX_RETRIES` retries on the same key (waits 1s, 2s), then cooldown 15s doubling to 5 min |
| HTTP 429 / quota | honours `Retry-After`/`retryDelay` (waits over 20s are not slept; cooldown instead), then cooldown 60s doubling to 15 min |
| During a cooldown | **no request is sent**; the router answers from the offline deterministic provider (labelled `OFFLINE`) |
| Invalid/expired key (400/401), 403, model not found (404) | no retry; slot is **blocked** and no traffic is sent until you fix the key, `gemini reload`, and `gemini check` succeeds |
| Other 400, empty or safety-blocked answer | reported; not retried; no cooldown |

Retries are bounded so the router's own retries are not stacked on top (a failure message always contains "unavailable").

## Usage and health tracking

Per slot: requests, successes, retries, rate-limit events, errors by category, last error (sanitised), last verified time,
and token counts from Google's `usageMetadata` when returned. **Remaining quota is not exposed by the Gemini API**, so none is shown.
Counters are in memory and reset when Aliena restarts.

## Troubleshooting

* **Slot shows Missing but I set it** - the variable must be in Aliena's own environment; restart the terminal/app. Empty or whitespace-only values count as Missing.
* **"malformed value"** - the value has spaces, quotes inside, a newline/CRLF, non-ASCII characters, a wrong length, or looks like a placeholder.
* **Configured but "not verified yet"** - nothing has succeeded yet. Run `gemini check N`. Aliena never claims a connection otherwise.
* **"API key rejected"** - key invalid/expired/revoked. Create a new key, update the variable, `gemini reload`, `gemini check N`.
* **"access denied"** (403/precondition) - key restricted, API not enabled for the project, region not supported, or key disabled (e.g. reported leaked). Aliena will not work around this.
* **"model not available"** - check `GEMINI_MODEL`; the model is never swapped automatically.
* **Rate limited / cooling down** - wait for the countdown, reduce usage, or wait for your quota to reset; Aliena will not use another key to bypass it. Switching accounts is your explicit choice (`gemini use N`) and subject to Google's terms.
* **Network error / timeout** - check connectivity, proxy and firewall; HTTPS to `generativelanguage.googleapis.com` is required.
* **Same key in two slots** - the second is flagged duplicate and cannot be selected.
* **Answers say OFFLINE/deterministic** - Gemini was unavailable (missing key, cooldown, blocked); the labelled offline provider answered. This is the pre-existing fallback; no paid fallback is added.
* **Billing** - Aliena cannot see whether a key belongs to a free or billing-enabled project. If you do not want charges, only configure keys from projects without billing.

## Security

Keys are read from environment variables only, held in a redacting wrapper, sent only in the `x-goog-api-key` header over HTTPS to
`generativelanguage.googleapis.com` (other hosts, redirects and URL-embedded keys are refused), and scrubbed from errors and logs.
If a key is ever exposed, revoke it at Google and create a new one. Never commit `.env`.

## Limitations

The settings interface is a text command / CLI / view-model; no PyQt settings widget was written. The real HTTPS transport was
exercised only through mocks (no network or real keys were available when this was built), so a first live `gemini check` is the real verification.
Counters are not persisted. Only text prompts are supported on the multi-account path.
