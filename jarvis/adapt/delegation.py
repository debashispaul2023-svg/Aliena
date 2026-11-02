"""Limited parallel delegation.

Caller timeout is enforced. Workers may still finish in the background;
that is distinct from the caller returning.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
from typing import Callable


def delegate(
    tasks: list[tuple[str, Callable[[], dict]]],
    *,
    max_workers: int = 2,
    timeout: float = 5.0,
) -> list[dict]:
    results = []
    pool = ThreadPoolExecutor(max_workers=max_workers)
    started = time.perf_counter()
    try:
        futures = {pool.submit(fn): name for name, fn in tasks}
        done, pending = wait(futures, timeout=timeout)
        for fut in done:
            name = futures[fut]
            try:
                results.append({"agent": name, "ok": True, "result": fut.result()})
            except Exception as exc:
                results.append({"agent": name, "ok": False, "error": str(exc)})
        for fut in pending:
            fut.cancel()
            results.append(
                {
                    "agent": futures[fut],
                    "ok": False,
                    "error": "caller_timeout",
                    "cancelled": fut.cancel(),
                }
            )
    finally:
        # Do not wait for unfinished workers. Caller must return.
        pool.shutdown(wait=False, cancel_futures=True)
    results.append({"caller_elapsed": round(time.perf_counter() - started, 4)})
    return results
