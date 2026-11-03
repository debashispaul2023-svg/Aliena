# Feature 3 — Multi-Agent System

Status: COMPLETE

Default Orchestrator.run uses dependency-aware parallel waves via ready_tasks + run_independent.
Concurrency limit defaults to 4. _parallel_waves counts scheduler waves.

Preserved:
- Simple-task path
- Clarification WAITING + resume
- Conflict escalation
- Cancellation, retries, approval
- Memory continuity
- Agent enable/disable
- Phase 6F BLOCKED

Parallel evidence: test_default_run_parallel_overlap uses a Barrier so two independent tasks must overlap.
