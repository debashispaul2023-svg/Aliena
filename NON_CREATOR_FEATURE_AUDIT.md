# Non-Creator Feature Audit

Date: 2026-11-27
Base: c452841ced938c731b608b1030ee1fdad715739e
Creator Engine C1–C11: not touched.

## Summary

Most non-Creator modules already have real workflows and tests. Live external integrations remain unverified. One regression was found and fixed: HUD avatar timer after the emotion UI change.

## Findings

| Feature | Files | Current | Missing | Status |
|---------|-------|---------|---------|--------|
| Persistent Memory | jarvis/memory/store.py | save, search, update, archive, backup | live user data not re-verified | IMPLEMENTED, TESTED |
| AI Router | jarvis/ai/router.py | selection, timeout, mock mode labelled | live Gemini connection | PARTIALLY IMPLEMENTED, NOT VERIFIED |
| Voice | jarvis/voice/ | state machine, keyboard fallback | mic/STT hardware | PARTIALLY IMPLEMENTED, NOT VERIFIED |
| Desktop | jarvis/desktop/ | permissions, approval, mock adapter | real OS drivers | PARTIALLY IMPLEMENTED, NOT VERIFIED |
| Resources | jarvis/resources/ | download manager, SSRF checks | DNS rebinding proof | PARTIALLY IMPLEMENTED |
| Research | jarvis/research/ | notes, search, source attribution | live fetch | PARTIALLY IMPLEMENTED, NOT VERIFIED |
| Productivity | jarvis/productivity/ | tasks, reminders stored | notification delivery | IMPLEMENTED, delivery NOT VERIFIED |
| Plugins | jarvis/plugins/ | registry, approval | auto-exec intentionally blocked | IMPLEMENTED |
| Freelancer | jarvis/freelancer/ | drafts, approval | external submit blocked | IMPLEMENTED |
| HUD / Avatar | jarvis/app/main.py | emotion PNG + desktop pet | timer regression fixed | TESTED |

## Security

- Generated-code execution remains BLOCKED.
- No host command execution from user input.
- Downloaded resources are not auto-executed.
- Secrets are not logged in full.

## Tests added this pass

- Existing HUD toggle suite now passes after restoring avatar timer start/stop.
