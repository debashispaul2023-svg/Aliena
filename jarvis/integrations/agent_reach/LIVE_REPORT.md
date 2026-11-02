# Agent Reach live channel report (2026-11-02)

CLI 1.6.1. Checks are live. Doctor alone is not treated as proof.

| Channel | Check | Real retrieval | Evidence | Blocker |
|---------|-------|----------------|----------|---------|
| github | PASS (search+read, gh and github-api) | PASS search `python requests` → psf/requests | item URL https://github.com/psf/requests | none for public search/read |
| youtube | PASS (read, search, subtitle) | PASS search `python tutorial` → watch URL | yt-dlp backend | none for public search |
| web | PARTIAL (search+exa read PASS, jina read 401) | PASS search → docs.python.org | Exa backend | Jina read unauthorized |
| v2ex | PARTIAL (hot/node/user PASS, read TIMEOUT) | PASS hot topics | v2ex-api | topic read timed out |
| reddit | not added | NOT TESTED | doctor | `agent-reach add reddit` not run |
| linkedin | not added | NOT TESTED | doctor | needs add; login may be required |
| twitter | not added | NOT TESTED | doctor | needs add |
| bilibili | needs_setup | NOT TESTED | bili-cli missing | `agent-reach add bilibili` |

Optional channels were not added. No credentials stored.

Jarvis treats retrieved text as untrusted data via `normalizer.py`. No job submission. Phase 6F remains blocked.
