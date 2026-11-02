"""Interactive setup guidance. Does not invent credentials."""

from __future__ import annotations

import os
from pathlib import Path

from jarvis.adapt.mcp_diag import detect_runtime


def wizard() -> list[str]:
    steps: list[str] = []
    runtime = detect_runtime()
    if not runtime["node"]:
        steps.append("Install Node.js LTS, then rerun.")
    if not runtime["docker"]:
        steps.append("Docker optional. Sequential, filesystem, memory, fetch, and GitHub do not need it.")
    root = os.environ.get("JARVIS_FS_ROOT")
    if not root:
        steps.append("Set JARVIS_FS_ROOT to one allowed folder. Do not use /.")
    elif not Path(root).is_dir():
        steps.append("JARVIS_FS_ROOT must be an existing directory.")
    if not os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"):
        steps.append("Set GITHUB_PERSONAL_ACCESS_TOKEN for GitHub MCP. Do not commit it.")
    if not os.environ.get("POSTGRES_URL"):
        steps.append("Postgres stays disabled. Use crystaldba/postgres-mcp --access-mode=restricted only after a read-only DB user exists.")
    steps.append("Fetch: pip install mcp-server-fetch. Do not use the archived postgres server.")
    steps.append("Playwright: npx playwright install chromium, then configure domain allowlist.")
    steps.append("Memory MCP is optional. SQLite remains the source of truth.")
    return steps
