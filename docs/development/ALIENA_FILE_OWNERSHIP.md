# Aliena File Ownership

## Claude (Part A)

- `jarvis/config.py`
- `jarvis/logger.py`
- `jarvis/core/**`
- `jarvis/memory/**`
- `jarvis/ai/**`
- `jarvis/dev/**`
- `jarvis/skills/**`
- related core tests

## Grok (Part B)

- `jarvis/resources/**`
- `jarvis/voice/**`
- `jarvis/desktop/**`
- `jarvis/research/**`
- `jarvis/productivity/**`
- `jarvis/plugins/**`
- `jarvis/freelancer/**`
- related service tests

## Shared / do not silently edit

- `ROADMAP.md`
- `IMPLEMENTATION_STATUS.md`
- `ARCHITECTURE.md`
- `SECURITY.md`
- `KNOWN_LIMITATIONS.md`
- `DEFERRED_TESTING.md`
- `CHANGELOG.md`
- `jarvis/dev/phase6_status.json` (execution stays BLOCKED)

## Cannot be fully separated

- `jarvis/app/` wires core and services together.
- Resource acquisition is used by the orchestrator.
- Research security reuses Feature 6 URL validation.
- Desktop and freelancer both depend on approval patterns.

These stay in both workspaces as read context. Only the owner may modify them.
