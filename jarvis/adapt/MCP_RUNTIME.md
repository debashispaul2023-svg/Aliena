# MCP runtime handoff

## What is live here

| Server | Status |
|--------|--------|
| local jarvis MCP | CONNECTED + TOOLS_EXECUTED (ping) |
| github | NOT_CONNECTED — needs token + npx server |
| filesystem | NOT_CONNECTED — needs `JARVIS_FS_ROOT` |
| fetch | NOT_CONNECTED — needs `uvx` / Python fetch server |
| playwright | NOT_CONNECTED — needs browser runtime |
| postgres reference | BLOCKED (archived, unsafe) |
| crystaldba/postgres-mcp | AUDITED, not installed. Restricted mode exists. Docker missing. |
| sequential | NOT_CONNECTED |
| memory | NOT_CONNECTED. SQLite remains source of truth. |
| docker | NOT_CONNECTED. Docker not installed. Privileged denied. |

## Setup on your PC

1. Copy `mcp_config.example.json` and `.env.example`.
2. Install Node.js and Docker only if you want those servers.
3. Set `GITHUB_PERSONAL_ACCESS_TOKEN` and `JARVIS_FS_ROOT`.
4. Do not enable postgres reference server.
5. For Postgres, use `crystaldba/postgres-mcp` with `--access-mode=restricted` and a read-only DB user.

No external write, deploy, or payment was performed.
