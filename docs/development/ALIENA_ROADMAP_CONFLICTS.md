# Aliena Roadmap Conflicts

| Conflict | Documents/source | Evidence | Recommended resolution | Requires owner approval? |
|----------|------------------|----------|------------------------|--------------------------|
| Feature 1 omitted from ledger | `ROADMAP.md` vs `jarvis/FEATURE_LEDGER.md` | Roadmap lists Feature 1; ledger starts at Feature 2 | Add Feature 1 to ledger | No |
| Feature 4 status conflict | `ROADMAP.md` PARTIAL, `FEATURE_LEDGER.md` COMPLETE, `FEATURE4.md` COMPLETE for declared scope | Execution backend is BLOCKED | Keep PARTIAL until owner accepts blocked execution as declared complete | Yes |
| Feature 5 scope wording | Roadmap says COMPLETE (mocked); ledger says COMPLETE | Live Gemini not verified | Keep mocked/offline qualifier | No |
| Aliena vs Jarvis naming | Root docs say Aliena; package is `jarvis` | Package path remains `jarvis/` | Keep package name; use Aliena as product name | Yes |
| Historical ZIPs inside archive | `Aliena-build.zip` contains older ZIPs | `Jarvis-FULL-updated.zip` and others are nested | Treat nested ZIPs as historical, not current source | No |
| Freelancer outside 11-feature roadmap | `jarvis/freelancer/` exists; roadmap has no freelancer row | Approval module present | Track as additional subsystem, do not remove | Yes |
