#!/usr/bin/env python3
"""Focused checks for parallel transfer queue and process-tree cancel."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.cli import (  # noqa: E402
    ProtonDriveCli,
    TransferCancelled,
    kill_owned_process_tree,
)
from proton_drive_desktop.config import normalize_transfer_max_concurrency  # noqa: E402
from proton_drive_desktop.transfer_queue import TransferQueue, clamp_max_concurrency  # noqa: E402


def test_kill_owned_process_tree() -> None:
    proc = subprocess.Popen(["bash", "-c", "sleep 60"], start_new_session=True)
    assert proc.poll() is None
    kill_owned_process_tree(proc.pid, grace_seconds=1.0)
    assert proc.wait(timeout=5) != 0


def test_run_transfer_cancel_kills_tree() -> None:
    cli = ProtonDriveCli.__new__(ProtonDriveCli)
    cli.binary = "bash"
    cli._transfer_procs = {}
    cli._transfer_cancelled_pids = set()
    cli._transfer_lock = threading.Lock()
    outcome: list[str] = []

    def work() -> None:
        try:
            cli.run_transfer(["-c", "sleep 60"], timeout=30)
            outcome.append("ok")
        except TransferCancelled:
            outcome.append("cancelled")
        except Exception as exc:  # noqa: BLE001
            outcome.append(f"err:{exc}")

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    for _ in range(100):
        with cli._transfer_lock:
            procs = [p for p in cli._transfer_procs.values() if p.poll() is None]
        if procs:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("transfer process did not start")
    assert cli.cancel_transfer() is True
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert outcome == ["cancelled"]


def test_run_transfer_parallel_cancel_all() -> None:
    cli = ProtonDriveCli.__new__(ProtonDriveCli)
    cli.binary = "bash"
    cli._transfer_procs = {}
    cli._transfer_cancelled_pids = set()
    cli._transfer_lock = threading.Lock()
    outcomes: list[str] = []
    lock = threading.Lock()

    def work() -> None:
        try:
            cli.run_transfer(["-c", "sleep 60"], timeout=30)
            with lock:
                outcomes.append("ok")
        except TransferCancelled:
            with lock:
                outcomes.append("cancelled")
        except Exception as exc:  # noqa: BLE001
            with lock:
                outcomes.append(f"err:{exc}")

    threads = [threading.Thread(target=work, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for _ in range(100):
        with cli._transfer_lock:
            alive = [p for p in cli._transfer_procs.values() if p.poll() is None]
        if len(alive) >= 2:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("parallel transfer processes did not start")
    assert cli.cancel_transfer() is True
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert outcomes == ["cancelled", "cancelled"]


def test_transfer_queue_serial_when_max_one() -> None:
    order: list[int] = []
    done = threading.Event()
    queue = TransferQueue(cancel_cli=lambda: False, max_concurrency=1, on_idle=done.set)

    def make_runner(n: int):
        def runner(_on_progress):
            order.append(n)
            time.sleep(0.05)
            return n

        return runner

    queue.enqueue("upload", "a", make_runner(1))
    queue.enqueue("upload", "b", make_runner(2))
    queue.enqueue("download", "c", make_runner(3))
    assert done.wait(timeout=5)
    assert order == [1, 2, 3]
    assert queue.snapshot().total_count == 0


def test_transfer_queue_parallel_two_slots() -> None:
    gate = threading.Event()
    entered = threading.Semaphore(0)
    idle = threading.Event()
    finished: list[str] = []

    def on_finished(job, _result, _snap) -> None:
        finished.append(job.label)

    queue = TransferQueue(
        cancel_cli=lambda: False,
        max_concurrency=2,
        on_finished=on_finished,
        on_idle=idle.set,
    )

    def blocker(label: str):
        def runner(_on_progress):
            entered.release()
            assert gate.wait(timeout=5)
            return label

        return runner

    queue.enqueue("upload", "a", blocker("a"))
    queue.enqueue("upload", "b", blocker("b"))
    queue.enqueue("download", "c", blocker("c"))
    assert entered.acquire(timeout=2)
    assert entered.acquire(timeout=2)
    snap = queue.snapshot()
    assert snap.active_count == 2
    assert snap.pending_count == 1
    assert {j.label for j in snap.active} == {"a", "b"}
    gate.set()
    assert idle.wait(timeout=5)
    assert set(finished) == {"a", "b", "c"}
    assert queue.snapshot().total_count == 0


def test_transfer_queue_clear_pending() -> None:
    started = threading.Event()
    release = threading.Event()
    idle = threading.Event()
    finished: list[str] = []

    def on_finished(job, _result, _snap) -> None:
        finished.append(job.label)

    queue = TransferQueue(
        cancel_cli=lambda: False,
        max_concurrency=1,
        on_finished=on_finished,
        on_idle=idle.set,
    )

    def blocker(_on_progress):
        started.set()
        assert release.wait(timeout=5)
        return None

    def later(_on_progress):
        return None

    queue.enqueue("upload", "active", blocker)
    assert started.wait(timeout=2)
    queue.enqueue("upload", "pending-1", later)
    queue.enqueue("download", "pending-2", later)
    assert queue.snapshot().pending_count == 2
    assert queue.clear_pending() == 2
    assert queue.snapshot().pending_count == 0
    release.set()
    assert idle.wait(timeout=5)
    assert finished == ["active"]


def test_transfer_queue_cancel_active_advances() -> None:
    cli = ProtonDriveCli.__new__(ProtonDriveCli)
    cli.binary = "bash"
    cli._transfer_procs = {}
    cli._transfer_cancelled_pids = set()
    cli._transfer_lock = threading.Lock()

    finished: list[str] = []
    cancelled: list[str] = []
    idle = threading.Event()
    active_started = threading.Event()

    def on_finished(job, _result, _snap) -> None:
        finished.append(job.label)

    def on_error(job, exc, _snap) -> None:
        if isinstance(exc, TransferCancelled):
            cancelled.append(job.label)

    queue = TransferQueue(
        cancel_cli=cli.cancel_transfer,
        max_concurrency=1,
        on_started=lambda job, _snap: active_started.set() if job.label == "sleep" else None,
        on_finished=on_finished,
        on_error=on_error,
        on_idle=idle.set,
    )

    def sleep_runner(_on_progress):
        return cli.run_transfer(["-c", "sleep 60"], timeout=30)

    def quick_runner(_on_progress):
        return "done"

    queue.enqueue("upload", "sleep", sleep_runner)
    queue.enqueue("upload", "next", quick_runner)
    assert active_started.wait(timeout=5)
    for _ in range(100):
        with cli._transfer_lock:
            procs = [p for p in cli._transfer_procs.values() if p.poll() is None]
        if procs:
            break
        time.sleep(0.05)
    assert queue.cancel_active() is True
    assert idle.wait(timeout=10)
    assert cancelled == ["sleep"]
    assert finished == ["next"]


def test_clamp_concurrency() -> None:
    assert clamp_max_concurrency(0) == 1
    assert clamp_max_concurrency(99) == 4
    assert clamp_max_concurrency(None) == 2
    assert normalize_transfer_max_concurrency("3") == 3
    assert normalize_transfer_max_concurrency("nope") == 2


if __name__ == "__main__":
    test_kill_owned_process_tree()
    test_run_transfer_cancel_kills_tree()
    test_run_transfer_parallel_cancel_all()
    test_transfer_queue_serial_when_max_one()
    test_transfer_queue_parallel_two_slots()
    test_transfer_queue_clear_pending()
    test_transfer_queue_cancel_active_advances()
    test_clamp_concurrency()
    print("transfer queue checks passed")
