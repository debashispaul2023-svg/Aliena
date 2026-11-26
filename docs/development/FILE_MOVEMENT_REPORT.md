# File Movement Report

Root cleanup only. No code imports were rewritten.

Moved:

- Phase, handover, and status markdown files → `docs/development/`
- Audit and security reports → `docs/security/`
- `ARCHITECTURE.md` → `docs/architecture/`
- Existing ZIP packages → `archive/`

Kept at root:

- README.md
- requirements.txt
- run_jarvis.py
- pytest.ini
- jarvis/
- assets/
- databases
- configuration examples

Not moved because of compatibility risk:

- `jarvis_memory.db`
- `jarvis_resources.db`
- `jarvis_skills.db`
- `jarvis_config.json`
- emotion assets under `assets/aliena/emotions/`
