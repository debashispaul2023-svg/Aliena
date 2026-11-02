"""Hermes-inspired adaptations. Does not replace Jarvis.

Ideas adapted from NousResearch/hermes-agent:
- skill drafts need approval
- project context files
- checkpoints
- optional scheduler
- MCP server registry (fail-closed)

Not a second assistant. Phase 6F remains blocked.
"""

from __future__ import annotations

__all__ = ["context", "checkpoints", "skills_adapt", "schedule", "mcp"]
