#!/usr/bin/env bash
# Reproducible MCP setup. Does not connect servers.
set -euo pipefail
echo "node: $(command -v node || echo MISSING)"
echo "npx: $(command -v npx || echo MISSING)"
echo "python: $(command -v python3 || echo MISSING)"
echo "docker: $(command -v docker || echo MISSING)"
echo "uvx: $(command -v uvx || echo MISSING)"
echo "GITHUB token: ${GITHUB_PERSONAL_ACCESS_TOKEN:+set}"
echo "JARVIS_FS_ROOT: ${JARVIS_FS_ROOT:-unset}"
echo "POSTGRES_URL: ${POSTGRES_URL:+set}"
echo
echo "Do not enable archived postgres server."
echo "Postgres alternative: crystaldba/postgres-mcp --access-mode=restricted"
echo "Filesystem root required before connect."
echo "No privileged Docker."
