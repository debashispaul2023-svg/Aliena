# Part B Integration Handover

Shared APIs required from Claude:

- config
- logger
- memory store
- orchestrator
- mocked AI router
- phase6_status.json must stay BLOCKED

Integration steps:

1. Copy Claude-owned files from Part A.
2. Copy Grok-owned files from this package.
3. Do not overwrite the three baseline databases.
4. Resolve shared docs by status.
5. Run focused tests for both sides.
