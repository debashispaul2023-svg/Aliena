# Security & Hardening Audit — Post-Fix Report

**Date:** 2026-11-26  
**Scope:** Four approved findings only (power control, dependency pins, .gitignore / local state, calculator).  
**Constraints observed:** ZERO feature loss · ZERO data loss · backward compatibility · no Git history rewrite · no deletion of existing DBs/logs from tree · no package rename.

## Summary

| # | Finding | Status | Evidence |
|---|---------|--------|----------|
| 1 | Power control: sleep lacked confirm; used `os.system` | **FIXED** | Confirmation required for sleep/shutdown/restart; all invocations now `subprocess.run(..., shell=False)` |
| 2 | Dependencies unpinned | **FIXED** | Exact pins in `requirements.txt` + `requirements.lock`; package names unchanged |
| 3 | Local state / DBs not ignored | **FIXED** | `*.db`, env files, editor noise added to `.gitignore`. Existing DB files left in tree (no deletion without separate approval) |
| 4 | Calculator used `eval` | **FIXED** | Replaced by AST-based `_safe_eval_math`; same ops, precedence, error path; regression tests added |

**Pending (out of approved scope):** privacy note for under-18 sharing; live Gemini verification; full git-history secret scan.

## 1. Power control (`jarvis/app/main.py`)

**Before:**  
- Shutdown / restart: spoken “confirm” required.  
- Sleep: no confirmation.  
- All three used `os.system(...)`.

**After:**  
- Sleep now asks “Say confirm sleep within 10 seconds…”.  
- All three use `subprocess.run([arg, ...], shell=False, check=False)`.  
- Windows sleep keeps the classic `rundll32.exe powrprof.dll,SetSuspendState` entry-point form.  
- Capability set unchanged (Windows / Darwin / Linux suspend/shutdown/restart).

**Verification:** source inspection confirms no `os.system` remains inside `power_control`; confirmation branch present for sleep.

## 2. Dependencies

**Before:**  
```
requests>=2.28
pytest>=7.0
google-generativeai   # unpinned
… many unpinned optional packages
```

**After:** exact pins in `requirements.txt` and `requirements.lock`.  
- Kept package name `google-generativeai` (code imports it); did **not** migrate to `google-genai` (would be a breaking rename).  
- Pins chosen from the original lower-bound series; no major-version force-upgrades of the AI or GUI stacks.

**pip-audit:** could not complete inside this environment (venv/ensurepip unavailable). Recommend running `pip-audit -r requirements.txt` on a developer machine before any public release.

## 3. Git / local-state exclusions

**Before:** `.gitignore` lacked `*.db`; sample DBs and `jarvis.log` were present in the distribution ZIP.

**After:**  
```
*.db
jarvis_memory.db
jarvis_resources.db
jarvis_skills.db
*.sqlite
*.sqlite3
.env
.env.*
!.env.example
… editor/OS noise
```
Existing database files and logs were **not** deleted from the working tree or history (would require separate explicit approval).

## 4. Calculator

**Before:**  
```python
result = eval(expr, {"__builtins__": {}}, {})
```
with a character whitelist.

**After:** pure-AST walker (`_safe_eval_math`) that accepts only:
- numeric constants  
- `+ - * / // % **`  
- unary `+ -`  
- parentheses  

Same whitelist pre-filter, same spoken error messages, same word-to-operator replacements.  
Regression tests: `jarvis/tests/test_calculator_safe.py` (6 tests, all passing).

## Feature / data preservation checklist

- [x] Power-control verbs and OS-specific commands preserved  
- [x] Calculator supported expression set and error behaviour preserved  
- [x] No database schema or content modified  
- [x] No files removed from the distribution tree  
- [x] No Git history rewrite  
- [x] Import names of third-party packages unchanged  
- [x] Existing test suite structure untouched (only added one new test file)

## Modified files

1. `jarvis/app/main.py` — safe math evaluator + power_control hardening  
2. `.gitignore` — local-state exclusions  
3. `requirements.txt` — exact pins  
4. `requirements.lock` — lock companion  
5. `jarvis/tests/test_calculator_safe.py` — new regression tests  
6. `AUDIT.md` — this report  

## Baseline test note

Full suite was not re-executed in this sandbox (heavy optional desktop/voice deps + missing system packages). Targeted calculator tests: **6/6 passed**. Recommend running `pytest jarvis/tests/ -q` on a machine with the pinned optional packages installed before shipping.

## Residual recommendations (not applied)

- Run `pip-audit` and address any CVEs on a full install.  
- Consider a future, approved migration from `google-generativeai` → `google-genai` with import shims.  
- If the public repo should never contain sample DBs, open a separate ticket to purge them from history after review.
