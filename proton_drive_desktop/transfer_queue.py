"""In-memory transfer queue: one active CLI process at a time."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .cli import TransferProgress


ProgressCallback = Callable[[TransferProgress], None]
JobRunner = Callable[[ProgressCallback | None], Any]


@dataclass(frozen=True)
class TransferJob:
    job_id: int
    kind: str
    label: str
    runner: JobRunner


@dataclass(frozen=True)
class QueueSnapshot:
    active: TransferJob | None
    pending: tuple[TransferJob, ...]

    @property
    def pending_count(self) -> int:
        return len(self.pending)

    @property
    def total_count(self) -> int:
        return (1 if self.active is not None else 0) + self.pending_count


class TransferQueue:
    """Serialize uploads/downloads so only one owned CLI process runs at a time."""

    def __init__(
        self,
        *,
        cancel_cli: Callable[[], bool],
        on_started: Callable[[TransferJob, QueueSnapshot], None] | None = None,
        on_progress: Callable[[TransferProgress, QueueSnapshot], None] | None = None,
        on_finished: Callable[[TransferJob, Any, QueueSnapshot], None] | None = None,
        on_error: Callable[[TransferJob, BaseException, QueueSnapshot], None] | None = None,
        on_idle: Callable[[], None] | None = None,
        on_changed: Callable[[QueueSnapshot], None] | None = None,
    ) -> None:
        self._cancel_cli = cancel_cli
        self._on_started = on_started
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._on_error = on_error
        self._on_idle = on_idle
        self._on_changed = on_changed
        self._lock = threading.Lock()
        self._pending: deque[TransferJob] = deque()
        self._active: TransferJob | None = None
        self._next_id = 1
        self._worker: threading.Thread | None = None

    def snapshot(self) -> QueueSnapshot:
        with self._lock:
            return QueueSnapshot(self._active, tuple(self._pending))

    def enqueue(self, kind: str, label: str, runner: JobRunner) -> TransferJob:
        with self._lock:
            job = TransferJob(self._next_id, kind, label, runner)
            self._next_id += 1
            self._pending.append(job)
            snap = QueueSnapshot(self._active, tuple(self._pending))
            need_worker = self._worker is None or not self._worker.is_alive()
        self._emit_changed(snap)
        if need_worker:
            self._start_worker()
        return job

    def cancel_active(self) -> bool:
        """Kill the owned process tree of the active transfer."""
        return self._cancel_cli()

    def clear_pending(self) -> int:
        """Drop queued (not yet started) jobs. Returns how many were removed."""
        with self._lock:
            cleared = len(self._pending)
            self._pending.clear()
            snap = QueueSnapshot(self._active, ())
        self._emit_changed(snap)
        return cleared

    def cancel_all(self) -> int:
        """Clear pending jobs and cancel the active process tree."""
        cleared = self.clear_pending()
        self.cancel_active()
        return cleared

    def _emit_changed(self, snap: QueueSnapshot) -> None:
        if self._on_changed is not None:
            self._on_changed(snap)

    def _start_worker(self) -> None:
        def work() -> None:
            while True:
                with self._lock:
                    if not self._pending:
                        self._active = None
                        self._worker = None
                        snap = QueueSnapshot(None, ())
                        idle = True
                    else:
                        job = self._pending.popleft()
                        self._active = job
                        snap = QueueSnapshot(job, tuple(self._pending))
                        idle = False
                if idle:
                    self._emit_changed(snap)
                    if self._on_idle is not None:
                        self._on_idle()
                    return
                self._emit_changed(snap)
                if self._on_started is not None:
                    self._on_started(job, snap)

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
                        if self._active is job:
                            self._active = None

        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            thread = threading.Thread(target=work, daemon=True, name="transfer-queue")
            self._worker = thread
            thread.start()
