# MCP activation results (verified)

| Server | Status | Evidence |
|--------|--------|----------|
| sequential | CONNECTED + TOOLS_EXECUTED | handshake + `sequentialthinking` returned thoughtNumber 1 |
| filesystem | CONNECTED + TOOLS_EXECUTED | restricted temp root + `list_directory` listed hello.txt |
| memory | CONNECTED + TOOLS_EXECUTED | `read_graph` returned empty entities. SQLite remains source of truth. |
| github | NOT_CONNECTED | token missing |
| fetch | NOT_CONNECTED | package exists on PyPI (`mcp-server-fetch`). Not installed in this run. |
| playwright | NOT_CONNECTED | browser not installed |
| postgres reference | BLOCKED | archived + unsafe |
| crystaldba/postgres-mcp | AUDITED | native install possible via pipx. Not enabled. |
| docker | NOT_CONNECTED | docker missing. Privileged denied. |

## PC setup

1. Install Node.js LTS.
2. `export JARVIS_FS_ROOT=/path/to/one/folder` — never `/`.
3. `export GITHUB_PERSONAL_ACCESS_TOKEN=...` — do not commit.
4. Sequential: `npx -y @modelcontextprotocol/server-sequential-thinking`
5. Filesystem: `npx -y @modelcontextprotocol/server-filesystem "$JARVIS_FS_ROOT"`
6. Memory: `npx -y @modelcontextprotocol/server-memory`
7. Fetch: `pip install mcp-server-fetch` then `python -m mcp_server_fetch`
8. Playwright: `npx playwright install chromium`
9. Postgres: do not use archived server. Optional: `pipx install postgres-mcp` with `--access-mode=restricted` and a read-only user.
10. Docker is optional.

Run `python -m jarvis.adapt.mcp_wizard` or call `wizard()` for missing items.
