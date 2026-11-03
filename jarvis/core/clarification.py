"""Clarification state. Answers resume the same task."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClarificationSession:
    task_id: str
    question: str
    answer: str | None = None
    closed: bool = False

    def reply(self, text: str) -> None:
        self.answer = text.strip()
        self.closed = True


class ClarificationCenter:
    def __init__(self) -> None:
        self.sessions: dict[str, ClarificationSession] = {}

    def ask(self, task_id: str, question: str) -> ClarificationSession:
        session = ClarificationSession(task_id=task_id, question=question)
        self.sessions[task_id] = session
        return session

    def needs_clarification(self, text: str) -> str | None:
        low = text.lower().strip()
        if low in {"do it", "fix this", "continue", "that one"}:
            return "Which task should I continue?"
        return None

    def resume(self, task_id: str, answer: str) -> ClarificationSession:
        session = self.sessions[task_id]
        session.reply(answer)
        return session
