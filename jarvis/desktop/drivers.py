"""Desktop driver interface. Real drivers stay UNVERIFIED without a desktop OS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DriverResult:
    ok: bool
    status: str
    executed: bool = False


class DesktopDriver:
    name = "base"

    def available(self) -> bool:
        return False

    def move(self, x: int, y: int, *, approved: bool) -> DriverResult:
        return DriverResult(False, "UNSUPPORTED", False)


class MockDesktopDriver(DesktopDriver):
    name = "mock"

    def available(self) -> bool:
        return True

    def move(self, x: int, y: int, *, approved: bool) -> DriverResult:
        if not approved:
            return DriverResult(False, "APPROVAL_REQUIRED", False)
        return DriverResult(True, "MOCK_ONLY", False)
