# Root Cleanup Report

Date: 2026-11-26
Base commit: 3b5c8d36b40d3f40dcdcb64979e2cfd5c9a98aac

## Kept at root

- README.md, .gitignore, .env.example
- requirements.txt, requirements.lock
- run_jarvis.py, pytest.ini
- CHANGELOG.md, ROADMAP.md, IMPLEMENTATION_STATUS.md
- KNOWN_LIMITATIONS.md, SECURITY.md, DEFERRED_TESTING.md, ARCHITECTURE.md
- mcp_config.example.json (referenced by docs)
- Runtime: jarvis_*.db, jarvis_config.json, jarvis.log

## Relocated

- 58 identical root documentation copies removed; content preserved in docs/
- KEYBOARD-STATUS.md, LATER-PC-SETUP.md, PROJECT-INVENTORY.md, SETUP-AND-CONFIGURATION.md, SHA256SUMS.txt → docs/development/
- Aliena-Structured-Secure.zip, JARVIS.py, orch_push.txt → archive/

## Verification

- Database hashes unchanged
- Content hashes of relocated files unchanged
- Shared contract files remain at root for jarvis/core/contract_check.py
