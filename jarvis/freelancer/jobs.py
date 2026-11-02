"""Job analysis and matching. Estimates only — not guaranteed outcomes."""

from __future__ import annotations

from typing import Any

SCAM_HINTS = ("pay upfront", "wire transfer", "whatsapp only", "gift card", "crypto only")


def analyze_job(job: dict[str, Any], skills: list[str]) -> dict[str, Any]:
    text = f"{job.get('title','')} {job.get('description','')}".lower()
    matched = [s for s in skills if s.lower() in text]
    budget = str(job.get("budget") or "")
    risks = [h for h in SCAM_HINTS if h in text]
    if "unpaid" in text or "exposure" in text:
        risks.append("unpaid_or_exposure")
    score = 40 + 15 * len(matched) - 25 * len(risks)
    if budget:
        score += 5
    score = max(0, min(100, score))
    return {
        "matched_skills": matched,
        "risks": risks,
        "suitability_score": score,
        "difficulty": "high" if "senior" in text or "architect" in text else "medium",
        "note": "Score is an estimate, not a success guarantee.",
    }


def filter_jobs(jobs: list[dict[str, Any]], min_score: float = 0) -> list[dict[str, Any]]:
    return [j for j in jobs if float(j.get("score") or 0) >= min_score]
