# Creator Engine security test report

Environment: Python 3.12.3, unittest (pytest unavailable offline). Date of run: see IMPLEMENTATION_STATUS.md.
This is an **internal** audit by the implementing agent, not an independent review.

## Result
`python3 -m unittest` over the 10 Creator test modules: **Ran 228 tests, OK**.

## Controls tested (`jarvis/tests/test_creator_security_audit.py` and per-phase suites)
* AST audit of every `jarvis/creator/*.py`: no imports of subprocess/socket/http/urllib/requests/importlib/pickle/ctypes/etc.,
  no `eval/exec/__import__/system/popen`, no `shell=`, `compile` only as `re.compile`.
  (This audit found and removed a dynamic `importlib` use in `composers.py`.)
* Gate matrix over every action: always-blocked actions (`execute_code`, `run_generated_script`, `run_downloaded_code`, `run_plugin`,
  `workspace_escape`) are denied with every approval shape; every approval-required action is denied without, and allowed only with, an
  approval for that exact action whose target (if set) equals the project; unknown/mis-cased actions are denied; every decision is audited.
* Path-boundary fuzz (1500 hostile paths, seeded): nothing written outside the project, no control-dir writes, no symlinks, integrity holds.
* Full end-to-end footprint: all files inside the Creator root, no symlinks/temp files/bytecode/executables, audit chain intact, persisted audit free of secrets.
* Generated artifacts are non-executable data (ZIP entries mode 0644). Preview files contain no scripts, no event handlers, CSP `default-src 'none'`.
* Existing `ExecutionGate` still raises `IsolationNotVerified`; `phase6_status.json` still says `execution: BLOCKED`.
* Hostile inputs: injection via spec text (HTML/JS/Python/SQL contexts), colour values, identifiers, template paths, symlinks, cross-project access.

## NOT verified / residual risk
* **No OS-level isolation exists.** Generated-code execution is therefore blocked everywhere; runtime/unit/integration/build/browser tests are never run.
* Workspace isolation is application-level (path validation + symlink refusal): a concurrent local process could race check-then-write (TOCTOU).
* Agent timeouts are checked after the call returns (not pre-emptive).
* Static analysis is heuristic: structural scanners can miss semantic errors and mis-parse unusual JS (regex literals).
* The PyQt shell and the `main.py` hook were not run (GUI dependencies unavailable); the hook was verified by syntax/AST tests and handler tests only.
* Live AI providers were never contacted; only the offline deterministic provider and fakes were exercised.
