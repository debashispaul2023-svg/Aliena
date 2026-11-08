# Feature 5 — AI Provider Router & Fallback

Status: COMPLETE for declared scope.

Implemented:
- Provider registry and selection
- Preferred provider + fallback chain
- Retryable vs non-retryable errors
- Circuit breaker per provider
- Deterministic offline fallback
- No live API key required for tests

Environment:
- JARVIS_AI_PROVIDER
- JARVIS_AI_FALLBACK
- JARVIS_AI_MAX_RETRIES
- GEMINI_API_KEY (optional, never logged)

Not verified live:
- Real Gemini network calls in this sandbox
