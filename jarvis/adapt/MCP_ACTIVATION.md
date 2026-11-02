# MCP external activation (2026-11-03)

Runtime in this workspace:
- Node v20.20.2, npm 10.8.2, npx present
- Python 3.10.21
- Docker missing
- uvx missing
- No GitHub token, no POSTGRES_URL, no JARVIS_FS_ROOT

| Server | Status | Why |
|--------|--------|-----|
| local | CONNECTED + TOOLS_EXECUTED | previous local handshake |
| sequential | NOT_CONNECTED | npx probe hung, no handshake |
| filesystem | NOT_CONNECTED | root unset |
| github | NOT_CONNECTED | token missing |
| fetch | NOT_CONNECTED | uvx missing |
| playwright | NOT_CONNECTED | browser runtime missing |
| postgres reference | BLOCKED | archived + unsafe |
| crystaldba/postgres-mcp | AUDITED | not installed, Docker missing |
| memory | NOT_CONNECTED | npx not verified |
| docker | NOT_CONNECTED | Docker missing, privileged denied |

No external server was marked CONNECTED.
SQLite memory unchanged. Phase 6F blocked.
