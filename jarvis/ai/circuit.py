"""Simple circuit breaker. Opens after consecutive failures.

Backward compatible: ``CircuitBreaker()`` and ``CircuitBreaker(limit)`` behave as
before (``.failures``, ``.open``, ``record_*``). New in Phase 6: after
``cooldown_s`` seconds an open breaker lets ONE trial call through (half-open) so
a transient outage cannot lock a provider out forever. A success closes it, a
failure re-opens it and restarts the cooldown.
"""

from __future__ import annotations

import time
from typing import Callable, Optional


class CircuitBreaker:
    def __init__(self, limit: int = 3, cooldown_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.cooldown_s = max(0.0, cooldown_s)
        self._clock = clock
        self.failures = 0
        self.open = False
        self.opened_at: Optional[float] = None

    def record_success(self) -> None:
        self.failures = 0
        self.open = False
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.limit:
            self.open = True
            self.opened_at = self._clock()  # (re)start cooldown, also after a failed half-open trial

    def allow(self) -> bool:
        """True when closed, or when open but the cooldown has elapsed (half-open trial)."""
        if not self.open:
            return True
        if self.opened_at is None:
            return False
        return (self._clock() - self.opened_at) >= self.cooldown_s
