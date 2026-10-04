"""In-process job executor (ThreadPoolExecutor) plus an in-memory event bus for live progress (SSE).

Job state is not kept here: each run's run.json is the source of truth, so a restart loses nothing except the
running thread (those runs are marked `interrupted` on startup and can be resumed).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from app.core.logging import get_logger
from app.jobs import pipeline
from app.jobs.run_state import RunTracker
from app.storage.repository import Repository
from app.storage.schemas import Run

log = get_logger("executor")


class EventBus:
    """Fan-out of run events to any number of subscribers (one queue per SSE connection)."""

    def __init__(self) -> None:
        self._subs: dict[str, list[queue.Queue[dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, run_id: str) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subs = self._subs.get(run_id, [])
            if q in subs:
                subs.remove(q)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs.get(event.get("run_id", ""), []))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # a stalled browser tab must not block the run


class JobExecutor:
    def __init__(self, repo: Repository, max_workers: int = 2) -> None:
        self.repo = repo
        self.bus = EventBus()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qap-run")
        self._trackers: dict[str, RunTracker] = {}
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        run: Run,
        overrides: dict[str, Any] | None = None,
        target: Callable[[Repository, RunTracker, dict[str, Any] | None], None] | None = None,
    ) -> None:
        tracker = RunTracker(self.repo, run, listeners=[self.bus.publish])
        with self._lock:
            if run.id in self._futures and not self._futures[run.id].done():
                raise RuntimeError(f"Run {run.id} is already running")
            self._trackers[run.id] = tracker
            self._futures[run.id] = self._pool.submit(
                target or pipeline.execute, self.repo, tracker, overrides
            )

    def is_running(self, run_id: str) -> bool:
        with self._lock:
            fut = self._futures.get(run_id)
            return bool(fut and not fut.done())

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            tracker = self._trackers.get(run_id)
        if tracker and self.is_running(run_id):
            tracker.cancel_requested.set()
            return True
        return False

    def shutdown(self) -> None:
        for tracker in list(self._trackers.values()):
            tracker.cancel_requested.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
