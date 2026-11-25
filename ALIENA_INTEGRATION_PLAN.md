# Aliena Integration Plan

1. Verify both workspace ZIP hashes.
2. Compare change manifests.
3. Detect overlapping edits. Shared files have one owner.
4. Merge Part A first, then Part B against the updated shared contracts.
5. Do not overwrite databases. Apply migrations only.
6. Run module-level integration tests after merge.
7. Produce one unified Aliena ZIP.
8. Keep Feature 4 Phase 6F BLOCKED.
9. Do not claim production readiness.

This partitioning phase does not implement new features.
