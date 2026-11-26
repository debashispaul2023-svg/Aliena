# Features 4–7 Source Audit

Baseline ZIP SHA-256: `9f34b2d2df2a3fcbbdc2a97510275f30def3e5413e4d7d43a737f59d95213c38`

## Feature 4 — PARTIAL

Implemented in `jarvis/dev/drafts.py`, `sensitive_paths.py`, `workspace.py`, `execution_backend.py`:
- hash-bound drafts
- approval before apply
- sensitive path policy
- syntax check and rollback
- Phase 6F execution BLOCKED

Missing / limited:
- TOCTOU race protection is not claimed
- unusual secret filenames outside the explicit list are not covered
- live generated-code sandbox remains BLOCKED

Tests present: `jarvis/tests/test_sensitive_paths.py`

## Feature 5 — COMPLETE (mocked) / live UNVERIFIED

Implemented in `jarvis/ai/router.py` and `jarvis/ai/circuit.py`:
- preferred provider
- fallback
- non-retryable auth errors
- circuit breaker

Live Gemini is UNVERIFIED. No live success evidence in this audit.

## Feature 6 — PARTIAL

Implemented in `jarvis/resources/downloader.py` and `safety.py`:
- SSRF and private-host checks
- archive limit: 100 files / 5 MiB
- best-effort DNS re-resolve in downloader

Real-world DNS rebinding is not proven. Fixture tests exist in `test_feature6_final_gaps.py`.

## Feature 7 — PARTIAL / mic BLOCKED

Implemented in `jarvis/voice/session.py`:
- state machine
- voice settings
- microphone status defaults to BLOCKED

Live STT and playback are UNVERIFIED. `/dev/snd` is absent in this environment.

## Recommended next phase

Stay on safe Feature 4–7 work only. Do not start Feature 8. Do not unblock Phase 6F.
