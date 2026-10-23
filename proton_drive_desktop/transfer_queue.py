"""In-memory transfer queue with configurable parallel CLI jobs."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .cli import TransferProgress


ProgressCallback = Callable[[TransferProgress], None]
JobRunner = Callable[[ProgressCallback | None], Any]

DEFAULT_MAX_CONCURRENCY = 2
MIN_MAX_CONCURRENCY = 1
MAX_MAX_CONCURRENCY = 4


def clamp_max_concurrency(value: int | float | None) -> int:
    """Clamp parallel transfer slots to ``[1, 4]``; invalid → 2."""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MAX_CONCURRENCY
    if n < MIN_MAX_CONCURRENCY:
        return MIN_MAX_CONCURRENCY
    if n > MAX_MAX_CONCURRENCY:
        return MAX_MAX_CONCURRENCY
    return n


@dataclass(frozen=True)
class TransferJob:
    job_id: int
    kind: str
    label: str
    runner: JobRunner


@dataclass(frozen=True)
class QueueSnapshot:
    active: tuple[TransferJob, ...]
    pending: tuple[TransferJob, ...]

    @property
    def active_count(self) -> int:
        return len(self.active)

    @property
    def pending_count(self) -> int:
        return len(self.pending)

    @property
    def total_count(self) -> int:
        return self.active_count + self.pending_count

    @property
    def primary(self) -> TransferJob | None:
        """First active job, or None when idle."""
        return self.active[0] if self.active else None


class TransferQueue:
    """Run up to ``max_concurrency`` owned CLI transfer processes in parallel."""

    def __init__(
        self,
        *,
        cancel_cli: Callable[[], bool],
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        on_started: Callable[[TransferJob, QueueSnapshot], None] | None = None,
        on_progress: Callable[[TransferProgress, QueueSnapshot], None] | None = None,
        on_finished: Callable[[TransferJob, Any, QueueSnapshot], None] | None = None,
        on_error: Callable[[TransferJob, BaseException, QueueSnapshot], None] | None = None,
        on_idle: Callable[[], None] | None = None,
        on_changed: Callable[[QueueSnapshot], None] | None = None,
    ) -> None:
        self._cancel_cli = cancel_cli
        self._max_concurrency = clamp_max_concurrency(max_concurrency)
        self._on_started = on_started
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._on_error = on_error
        self._on_idle = on_idle
        self._on_changed = on_changed
        self._lock = threading.Lock()
        self._pending: deque[TransferJob] = deque()
        self._active: dict[int, TransferJob] = {}
        self._next_id = 1
        self._worker_count = 0

    @property
    def max_concurrency(self) -> int:
        with self._lock:
            return self._max_concurrency

    def set_max_concurrency(self, value: int) -> None:
        """Update the parallel slot limit and start waiting jobs if capacity grows."""
        with self._lock:
            self._max_concurrency = clamp_max_concurrency(value)
        self._pump()

    def snapshot(self) -> QueueSnapshot:
        with self._lock:
            return QueueSnapshot(tuple(self._active.values()), tuple(self._pending))

    def enqueue(self, kind: str, label: str, runner: JobRunner) -> TransferJob:
        with self._lock:
            job = TransferJob(self._next_id, kind, label, runner)
            self._next_id += 1
            self._pending.append(job)
            snap = QueueSnapshot(tuple(self._active.values()), tuple(self._pending))
        self._emit_changed(snap)
        self._pump()
        return job

    def cancel_active(self) -> bool:
        """Kill owned process trees of all currently running transfers."""
        return self._cancel_cli()

    def clear_pending(self) -> int:
        """Drop queued (not yet started) jobs. Returns how many were removed."""
        with self._lock:
            cleared = len(self._pending)
            self._pending.clear()
            snap = QueueSnapshot(tuple(self._active.values()), ())
        self._emit_changed(snap)
        return cleared

    def cancel_all(self) -> int:
        """Clear pending jobs and cancel every active process tree."""
        cleared = self.clear_pending()
        self.cancel_active()
        return cleared

    def _emit_changed(self, snap: QueueSnapshot) -> None:
        if self._on_changed is not None:
            self._on_changed(snap)

    def _pump(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                if len(self._active) >= self._max_concurrency:
                    return
                job = self._pending.popleft()
                self._active[job.job_id] = job
                self._worker_count += 1
                snap = QueueSnapshot(tuple(self._active.values()), tuple(self._pending))
            self._emit_changed(snap)
            if self._on_started is not None:
                self._on_started(job, snap)
            thread = threading.Thread(
                target=self._run_job,
                args=(job,),
                daemon=True,
                name=f"transfer-job-{job.job_id}",
            )
            thread.start()

    def _run_job(self, job: TransferJob) -> None:
        def progress_cb(progress: TransferProgress) -> None:
            if self._on_progress is not None:
                self._on_progress(progress, self.snapshot())

        try:
            result = job.runner(progress_cb)
        except Exception as exc:  # noqa: BLE001 — surfaced to UI via on_error
            if self._on_error is not None:
                self._on_error(job, exc, self.snapshot())
        else:
            if self._on_finished is not None:
                self._on_finished(job, result, self.snapshot())
        finally:
            with self._lock:
                self._active.pop(job.job_id, None)
                self._worker_count = max(0, self._worker_count - 1)
                snap = QueueSnapshot(tuple(self._active.values()), tuple(self._pending))
                maybe_idle = not self._active and not self._pending and self._worker_count == 0
            self._emit_changed(snap)
            still_idle = False
            if maybe_idle:
                with self._lock:
                    still_idle = not self._active and not self._pending and self._worker_count == 0
            if still_idle:
                if self._on_idle is not None:
                    self._on_idle()
            else:
                self._pump()
