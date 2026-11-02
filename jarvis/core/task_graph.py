"""Dependency graph scheduling for orchestrator tasks."""

from __future__ import annotations

from typing import Iterable

from .models import (
    TaskRecord,
    STATUS_PLANNED,
    STATUS_READY,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_WAITING,
    TERMINAL,
)


class CycleError(ValueError):
    pass


class UnknownDependencyError(ValueError):
    pass


class TaskGraph:
    """Manages task dependencies and readiness."""

    def __init__(self, tasks: Iterable[TaskRecord] | None = None) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        if tasks:
            for t in tasks:
                self.add(t)

    def add(self, task: TaskRecord) -> None:
        self._tasks[task.task_id] = task

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[TaskRecord]:
        return list(self._tasks.values())

    def validate(self) -> None:
        """Reject unknown deps and cycles before execution."""
        ids = set(self._tasks)
        for t in self._tasks.values():
            for dep in t.dependencies:
                if dep not in ids:
                    raise UnknownDependencyError(
                        f"Task {t.task_id} depends on unknown task {dep}"
                    )
        # Cycle detection via DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self._tasks}

        def visit(tid: str, stack: list[str]) -> None:
            color[tid] = GRAY
            stack.append(tid)
            for dep in self._tasks[tid].dependencies:
                if color[dep] == GRAY:
                    cycle = " -> ".join(stack[stack.index(dep) :] + [dep])
                    raise CycleError(f"Dependency cycle detected: {cycle}")
                if color[dep] == WHITE:
                    visit(dep, stack)
            stack.pop()
            color[tid] = BLACK

        for tid in list(self._tasks):
            if color[tid] == WHITE:
                visit(tid, [])

    def ready_tasks(self) -> list[TaskRecord]:
        """Tasks whose dependencies are all COMPLETED and not terminal themselves."""
        ready = []
        for t in self._tasks.values():
            if t.status in TERMINAL or t.cancelled:
                continue
            if t.status not in (STATUS_PLANNED, STATUS_READY, STATUS_WAITING):
                continue
            deps_ok = True
            for dep_id in t.dependencies:
                dep = self._tasks.get(dep_id)
                if dep is None or dep.status != STATUS_COMPLETED:
                    deps_ok = False
                    if dep is not None and dep.status in (STATUS_FAILED, STATUS_CANCELLED):
                        # blocked permanently by failed dep
                        if t.status != STATUS_FAILED:
                            t.status = STATUS_FAILED
                            t.error = f"Blocked by dependency {dep_id} status={dep.status}"
                    break
            if deps_ok:
                if t.status in (STATUS_PLANNED, STATUS_WAITING):
                    t.status = STATUS_READY
                ready.append(t)
        return ready

    def topological_order(self) -> list[TaskRecord]:
        """Return tasks in a valid dependency order. Raises on cycle."""
        self.validate()
        remaining = {tid: set(t.dependencies) for tid, t in self._tasks.items()}
        order: list[TaskRecord] = []
        available = [tid for tid, deps in remaining.items() if not deps]
        while available:
            available.sort()  # deterministic
            tid = available.pop(0)
            order.append(self._tasks[tid])
            for other, deps in remaining.items():
                if tid in deps:
                    deps.remove(tid)
                    if not deps and other not in [x.task_id for x in order]:
                        available.append(other)
        if len(order) != len(self._tasks):
            raise CycleError("Could not produce full topological order")
        return order

    def all_terminal(self) -> bool:
        return all(t.status in TERMINAL for t in self._tasks.values())

    def has_failures(self) -> bool:
        return any(t.status == STATUS_FAILED for t in self._tasks.values())
