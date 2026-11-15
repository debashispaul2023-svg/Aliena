"""Local productivity tasks. No external calendar writes without approval."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Task:
    title: str
    done: bool = False


class ProductivityBoard:
    def __init__(self) -> None:
        self.tasks: list[Task] = field(default_factory=list) if False else []

    def add(self, title: str) -> Task:
        task = Task(title=title.strip())
        if not task.title:
            raise ValueError("title required")
        self.tasks.append(task)
        return task

    def complete(self, title: str) -> bool:
        for task in self.tasks:
            if task.title == title:
                task.done = True
                return True
        return False
