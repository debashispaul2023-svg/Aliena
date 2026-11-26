# Aliena Source Inventory

| Module | Files | Responsibility |
|--------|-------|----------------|
| Core | `jarvis/core/orchestrator.py`, `parallel.py` | Task graph and parallel waves |
| Memory | `jarvis/memory/store.py` | SQLite persistent memory |
| Dev | `jarvis/dev/drafts.py`, `workspace.py`, `execution_backend.py` | Drafts, workspace jail, blocked execution |
| AI | `jarvis/ai/router.py`, `providers/` | Provider selection and fallback |
| Resources | `jarvis/resources/downloader.py`, `safety.py` | Downloads and SSRF checks |
| Voice | `jarvis/voice/session.py` | Voice state machine and mock pipeline |
| Desktop | `jarvis/desktop/automation.py` | Desktop facade, approval required |
| Research | `jarvis/research/knowledge.py` | Local HTTPS notes |
| Productivity | `jarvis/productivity/board.py` | Local task board |
| Plugins | `jarvis/plugins/registry.py` | Plugin registry, no auto-run |
| Freelancer | `jarvis/freelancer/approval.py`, `jobs.py`, `proposals.py` | Approval-gated freelance tools |
