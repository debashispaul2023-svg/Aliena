# Hermes feature adoption

Jarvis was not replaced. Ideas from NousResearch/hermes-agent were adapted.

| Hermes idea | Jarvis status |
|-------------|---------------|
| Self-improving skills | Draft + approval in `skills_adapt.py`. Not auto-activated. |
| Project context files | `context.py` loads AGENTS.md, CLAUDE.md, .hermes.md, SOUL.md, .cursorrules as untrusted. |
| Checkpoints | `checkpoints.py` copies files with hashes. Not a Git replacement. |
| Scheduler | Optional records. External actions need approval. No daemon. |
| MCP | Registry is fail-closed. No live session. |
| Provider routing | Existing `jarvis/ai/router.py` kept. No fake providers. |
| Voice | Existing Edge TTS kept. Telegram not added (no credentials). |

Phase 6F remains blocked.
