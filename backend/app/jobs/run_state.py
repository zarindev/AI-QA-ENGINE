"""Run lifecycle persisted in run.json: stage status, overall progress, heartbeat, token usage.

The tracker is the single writer of run.json while a run executes. Listeners (the SSE endpoint, the CLI
progress bar) receive every event; events are also appended to artifacts/logs/events.jsonl for replay.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from app.core.logging import get_logger
from app.storage.repository import Repository
from app.storage.schemas import STAGES, Run, TokenUsage, utcnow

log = get_logger("run")

STAGE_WEIGHTS = {
    "explore": 20,
    "understand": 8,
    "model": 4,
    "requirements": 8,
    "design": 10,
    "execute": 35,
    "verify": 10,
    "report": 5,
}

Listener = Callable[[dict[str, Any]], None]


class RunTracker:
    def __init__(self, repo: Repository, run: Run, listeners: list[Listener] | None = None) -> None:
        self.repo = repo
        self.run = run
        self.listeners: list[Listener] = list(listeners or [])
        self._lock = threading.RLock()
        self._last_save = 0.0
        self.cancel_requested = threading.Event()

    # ------------------------------------------------------------------ helpers

    def _emit(self, kind: str, **data: Any) -> None:
        event = {
            "type": kind,
            "run_id": self.run.id,
            "project": self.run.project_slug,
            "at": utcnow().isoformat(),
            **data,
        }
        try:
            self.repo.append_line(
                self.repo.run_path(self.run, "artifacts/logs/events.jsonl"),
                json.dumps(event, ensure_ascii=False, default=str),
            )
        except OSError as exc:
            log.warning("Could not append event: %s", exc)
        for listener in list(self.listeners):
            try:
                listener(event)
            except Exception as exc:  # a broken listener (closed SSE client) must not break the run
                log.debug("listener failed: %s", exc)

    def _recompute(self) -> None:
        total = done = 0.0
        for name, state in self.run.stages.items():
            if state.status == "skipped":
                continue
            weight = STAGE_WEIGHTS.get(name, 5)
            total += weight
            done += weight * (1.0 if state.status == "done" else state.progress)
        self.run.progress = round(100 * done / total, 1) if total else 0.0

    def save(self, force: bool = True) -> None:
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_save < 0.5:
                return
            self.run.heartbeat_at = utcnow()
            self._recompute()
            self.repo.save_run(self.run)
            self._last_save = now

    # ------------------------------------------------------------------ lifecycle

    def start(self, stages: list[str] | None = None) -> None:
        """Mark the run running. Stages not in `stages` are skipped (e.g. Phase 1 CLI runs explore + report)."""
        with self._lock:
            wanted = set(stages or STAGES)
            for name, state in self.run.stages.items():
                if name not in wanted and state.status != "done":
                    state.status = "skipped"
            self.run.status = "running"
            self.run.started_at = self.run.started_at or utcnow()
            self.run.error = ""
            self.save()
        self._emit("run_started", stages=sorted(wanted, key=STAGES.index))

    def stage_start(self, stage: str, message: str = "") -> None:
        with self._lock:
            st = self.run.stages[stage]
            st.status, st.progress, st.message, st.started_at = "running", 0.0, message, utcnow()
            self.run.stage, self.run.message = stage, message
            self.save()
        self._emit("stage_started", stage=stage, message=message)

    def stage_progress(self, stage: str, fraction: float, message: str = "", **extra: Any) -> None:
        if self.cancel_requested.is_set():
            raise RunCancelled()
        with self._lock:
            st = self.run.stages[stage]
            st.progress = max(0.0, min(1.0, fraction))
            if message:
                st.message = self.run.message = message
            self.save(force=False)
        self._emit(
            "progress",
            stage=stage,
            fraction=round(fraction, 3),
            message=message,
            overall=self.run.progress,
            **extra,
        )

    def stage_done(self, stage: str, message: str = "") -> None:
        with self._lock:
            st = self.run.stages[stage]
            st.status, st.progress, st.finished_at = "done", 1.0, utcnow()
            if message:
                st.message = message
            self.save()
        self._emit("stage_done", stage=stage, message=message, overall=self.run.progress)

    def usage_update(self, usage: TokenUsage) -> None:
        with self._lock:
            self.run.token_usage = usage
            self.save(force=False)
        self._emit("usage", tokens=usage.total, cost_usd=round(usage.cost_usd, 4))

    def complete(self, message: str = "Run finished") -> None:
        with self._lock:
            self.run.status = "completed"
            self.run.finished_at = utcnow()
            self.run.message = message
            self.save()
        self._emit("run_completed", message=message)

    def fail(self, error: str) -> None:
        with self._lock:
            self.run.status = "failed"
            self.run.error = error[:2000]
            self.run.finished_at = utcnow()
            st = self.run.stages.get(self.run.stage)
            if st and st.status == "running":
                st.status = "failed"
                st.message = error[:300]
            self.save()
        self._emit("run_failed", error=error[:2000])

    def cancel(self) -> None:
        with self._lock:
            self.run.status = "cancelled"
            self.run.finished_at = utcnow()
            self.save()
        self._emit("run_cancelled")


class RunCancelled(Exception):
    pass


HEARTBEAT_S = 20  # a working run writes run.json at least this often
STALE_AFTER_S = 90  # no heartbeat for this long → the process that ran it is gone


@contextmanager
def heartbeat(tracker: RunTracker, every_s: float = HEARTBEAT_S) -> Iterator[None]:
    """Keep `heartbeat_at` fresh while a job runs, even during long steps that report no progress, so another
    QA Pilot process opening the same workspace does not mistake the run for an abandoned one."""
    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(every_s):
            if tracker.run.status == "running":
                try:
                    tracker.save()
                except OSError as exc:
                    log.warning("heartbeat failed: %s", exc)

    thread = threading.Thread(target=beat, name=f"heartbeat-{tracker.run.id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()


def mark_interrupted_runs(repo: Repository, stale_after_s: int = STALE_AFTER_S) -> list[Run]:
    """On startup: a run still 'running' whose heartbeat stopped belongs to a process that died. Mark it resumable.
    Runs with a fresh heartbeat are left alone — another QA Pilot process may be working on them."""
    marked = []
    now = utcnow()
    for project in repo.list_projects():
        for run in repo.list_runs(project.slug):
            if run.status not in ("running", "pending") or run.started_at is None:
                continue
            beat = run.heartbeat_at or run.started_at
            if (now - beat).total_seconds() < stale_after_s:
                continue
            run.status = "interrupted"
            run.message = f"Interrupted during '{run.stage}' (QA Pilot was closed). Resume to continue."
            for state in run.stages.values():
                if state.status == "running":
                    state.status = "pending"
            repo.save_run(run)
            marked.append(run)
    return marked
