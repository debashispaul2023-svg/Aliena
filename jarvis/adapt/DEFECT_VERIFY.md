# Defect verification (2026-11-03)

## Delegation timeout

Previous defect: `delegate(..., timeout=0.03)` with a 0.25s worker returned after ~0.25s because the executor waited on shutdown.

Fix: `wait()` plus `shutdown(wait=False, cancel_futures=True)`.

Measured after fix: caller returned in **0.0306s**. Result included `caller_timeout`.

Caller timeout is not the same as worker termination. A running thread cannot be force-killed; `cancelled` was `False` because the worker had already started.

## SSRF

Previous defect: only exact hosts `127.0.0.1` and `0.0.0.0` were blocked.

After fix, blocked:

| URL | Result |
|-----|--------|
| 127.0.0.1 | BLOCKED |
| 10.0.0.1 | BLOCKED |
| 192.168.1.1 | BLOCKED |
| 169.254.169.254 | BLOCKED |
| [::1] | BLOCKED |
| [fc00::1] | BLOCKED |
| [::ffff:127.0.0.1] | BLOCKED |
| 0.0.0.0 | BLOCKED |
| localhost | BLOCKED |

DNS results that are private/loopback are rejected. Redirect following is not implemented in this adapter. DNS rebinding after the check is a residual limit: validation is at request time only.
