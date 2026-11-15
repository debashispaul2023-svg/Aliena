"""Bounded parallel runner for independent tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from jarvis.core.models import TaskRecord, STATUS_COMPLETED, STATUS_FAILED
from jarvis.core.task_graph import TaskGraph


def ready_tasks(graph: TaskGraph) -> list[TaskRecord]:
    done = {t.task_id for t in graph._tasks.values() if t.status == STATUS_COMPLETED}
    ready = []
    for task in graph._tasks.values():
        if task.status != "PLANNED":
            continue
        if all(dep in done for dep in task.dependencies):
            ready.append(task)
    return ready


def run_independent(tasks: list[TaskRecord], worker: Callable[[TaskRecord], dict], *, limit: int = 2) -> list[dict]:
    if not tasks:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=max(1, limit)) as pool:
        futures = {pool.submit(worker, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # isolate: one failing worker must not lose the others' results
                task = futures[future]
                task.status = STATUS_FAILED
                task.error = f"worker error: {type(exc).__name__}: {exc}"
                results.append({"id": task.task_id, "ok": False})
    return results
