# Aliena Shared Contract

## Ownership

- Claude owns shared core interfaces.
- Grok consumes them.
- Shared file changes need a documented proposal.

## Stable interfaces

- Config load/save in `jarvis/config.py`
- Memory store in `jarvis/memory/store.py`
- Orchestrator in `jarvis/core/orchestrator.py`
- Provider router in `jarvis/ai/router.py`
- Phase 6F status stays `BLOCKED` in `jarvis/dev/phase6_status.json`

## Rules

- No unrestricted generated-code execution.
- No live Gemini claim.
- No secret contents in audit logs.
- Databases `jarvis_memory.db`, `jarvis_resources.db`, `jarvis_skills.db` are protected baseline.
- Feature 9 research and Feature 10 productivity use their own stores.
- Approval required for destructive or external actions.

## Error convention

Fail closed. Return status strings such as `BLOCKED`, `UNSUPPORTED`, `APPROVAL_REQUIRED`. Do not fake success.
