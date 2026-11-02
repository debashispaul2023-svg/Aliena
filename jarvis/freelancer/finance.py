"""Local finance tracker. No payment execution."""

from __future__ import annotations

from jarvis.freelancer.store import FreelancerStore


def record_income(store: FreelancerStore, project: str, amount: float, currency: str = "USD") -> int:
    if amount < 0:
        raise ValueError("income amount must be non-negative")
    return store.add_earning(project, amount, "income", currency)


def record_expense(store: FreelancerStore, project: str, amount: float, currency: str = "USD") -> int:
    if amount < 0:
        raise ValueError("expense amount must be non-negative")
    return store.add_earning(project, -abs(amount), "expense", currency)


def platform_fee(amount: float, rate: float = 0.1) -> float:
    if rate < 0 or rate > 1:
        raise ValueError("rate must be between 0 and 1")
    return round(amount * rate, 2)


def summary(store: FreelancerStore) -> dict:
    return {"income_total": store.income_total()}
