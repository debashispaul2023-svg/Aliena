"""Simple circuit breaker. Opens after consecutive failures."""

from __future__ import annotations


class CircuitBreaker:
    def __init__(self, limit: int = 3):
        self.limit = limit
        self.failures = 0
        self.open = False

    def record_success(self) -> None:
        self.failures = 0
        self.open = False

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.limit:
            self.open = True

    def allow(self) -> bool:
        return not self.open
