"""Shared status vocabulary for Aliena (additive; nothing imports this yet except tests).

Values are copied *verbatim* from the strings already used in the code base so
that adopting these constants can never change behaviour:

* ``jarvis/dev/execution_backend.py``: UNAVAILABLE, BLOCKED, MOCKED, EXECUTED
* ``jarvis/core/models.py``: task status ``REQUIRES_APPROVAL``
* ``ALIENA_SHARED_CONTRACT.md`` error convention: BLOCKED, UNSUPPORTED, APPROVAL_REQUIRED
* Part B ``jarvis/desktop/engine.py`` emits ``"APPROVAL_REQUIRED"`` and ``"INVALID"``

NOTE: ``REQUIRES_APPROVAL`` (task lifecycle state) and ``APPROVAL_REQUIRED``
(fail-closed result string) are two different existing strings. They are kept
as two separate constants on purpose; aliasing one to the other would change
existing behaviour.

``MOCKED`` means application logic was exercised. It is NOT execution.
``EXECUTED`` is reserved: no Part A code path returns it (generated-code
execution is BLOCKED; see jarvis/dev/phase6_status.json).
"""

from __future__ import annotations

# Fail-closed result strings (shared contract)
BLOCKED = "BLOCKED"
UNSUPPORTED = "UNSUPPORTED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"

# Additional strings already in use
UNAVAILABLE = "UNAVAILABLE"
MOCKED = "MOCKED"
EXECUTED = "EXECUTED"  # reserved - never produced by Part A
INVALID = "INVALID"

# Task lifecycle state (core/models.py) - distinct from APPROVAL_REQUIRED
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"

# Feature status labels used in documentation
FEATURE_STATUSES = ("COMPLETE", "PARTIAL", "BLOCKED", "NOT STARTED", "UNVERIFIED")

FAIL_CLOSED_STATUSES = frozenset({BLOCKED, UNSUPPORTED, APPROVAL_REQUIRED, UNAVAILABLE, INVALID})

__all__ = [
    "BLOCKED",
    "UNSUPPORTED",
    "APPROVAL_REQUIRED",
    "UNAVAILABLE",
    "MOCKED",
    "EXECUTED",
    "INVALID",
    "REQUIRES_APPROVAL",
    "FEATURE_STATUSES",
    "FAIL_CLOSED_STATUSES",
]
