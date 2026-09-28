#!/usr/bin/env python3
"""Sync-folder worker checks. Full /my-files mirror is not run here."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_linux import config  # noqa: E402
from proton_drive_linux.cli import CliError, ProtonDriveCli, find_binary, join_path, node_name  # noqa: E402
from proton_drive_linux.config import parse_sync_status  # noqa: E402
from proton_drive_linux.sync import (  # noqa: E402
    activity_snapshot,
    due_for_pass,
    format_files_last_pass,
    format_last_error,
    format_status_line,
    format_when,
    format_worker_line,
    local_children,
    lock_holder_pid,
)


def test_official_cli_has_no_fuse() -> None:
    proc = subprocess.run(
        [find_binary(), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    text = f"{proc.stdout}\n{proc.stderr}".lower()
    assert "filesystem download" in text or "filesystem list" in text
    assert "fuse" not in text
    assert " mount" not in text
    assert "\nmount" not in text
    assert "filesystem mount" not in text
    print("cli has no FUSE/mount command")


def test_local_children_skips_hidden(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-linux-sync-children")
    folder.mkdir(parents=True, exist_ok=True)
    visible = folder / "notes.txt"
    hidden = folder / ".hidden"
    visible.write_text("ok", encoding="utf-8")
    hidden.write_text("no", encoding="utf-8")
    names = [path.name for path in local_children(folder)]
    assert names == ["notes.txt"]
    visible.unlink()
    hidden.unlink()


def _isolate_sync_config(folder: Path):
    original = (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.SYNC_LOCK_PATH,
        config.GUI_BUSY_PATH,
    )
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    config.SYNC_STATUS_PATH = folder / "sync-status.json"
    config.SYNC_LOCK_PATH = folder / "sync.lock"
    config.GUI_BUSY_PATH = folder / "gui-busy"
    return original


def _restore_sync_config(original) -> None:
    (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.SYNC_LOCK_PATH,
        config.GUI_BUSY_PATH,
    ) = original


def test_parse_sync_status() -> None:
    parsed = parse_sync_status(
        '{"state":"idle","last_finished":"2026-09-28T12:00:00+00:00","last_error":"","last_pull":"3","last_push":1,"pid":0,"message":"Synced 3 remote and 1 local item(s)"}'
    )
    assert parsed["state"] == "idle"
    assert parsed["last_pull"] == 3
    assert parsed["last_push"] == 1
    assert parsed["last_success"] == "2026-09-28T12:00:00+00:00"
    assert parsed["last_error"] == ""
    failed = parse_sync_status(
        {
            "state": "error",
            "last_finished": "2026-09-28T13:00:00+00:00",
            "last_error": "download notes.txt: timeout\nupload draft.md: 422",
            "last_pull": 1,
            "last_push": 0,
            "last_success": "2026-09-28T12:00:00+00:00",
        }
    )
    assert failed["last_error"].startswith("download notes.txt")
    assert failed["last_success"] == "2026-09-28T12:00:00+00:00"
    assert failed["last_pull"] == 1
    empty = parse_sync_status("not-json")
    assert empty["state"] == "idle"
    assert empty["last_error"] == ""
    assert parse_sync_status(None)["state"] == "idle"
    assert format_when("") == "Never"
    assert "2026-09-28" in format_when("2026-09-28T12:00:00+00:00")
    assert format_files_last_pass(3, 1, had_pass=True) == "3 remote, 1 local copied"
    assert format_files_last_pass(0, 0, had_pass=False) == "No completed pass yet"
    assert format_last_error("") == "None"
    assert format_last_error("download a: timeout\nupload b: 422") == "download a: timeout"
    long_err = "e" * 200
    assert format_last_error(long_err).endswith("...")
    assert format_worker_line(enabled=False, pid=9) == "Off"
    assert format_worker_line(enabled=True, pid=0) == "Stopped"
    assert format_worker_line(enabled=True, pid=4242) == "Running (pid 4242)"
    print("status parsing ok")


def test_status_helpers(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-linux-sync-status")
    folder.mkdir(parents=True, exist_ok=True)
    original = _isolate_sync_config(folder)
    try:
        config.save({"theme": "dark", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": True})
        config.save_sync_status(
            {
                "state": "idle",
                "last_finished": "2026-09-28T12:00:00+00:00",
                "last_success": "2026-09-28T12:00:00+00:00",
                "last_error": "",
                "last_pull": 4,
                "last_push": 2,
                "message": "Synced 4 remote and 2 local item(s)",
            }
        )
        snap = activity_snapshot()
        assert snap["worker"] == "Stopped"
        assert snap["files"] == "4 remote, 2 local copied"
        assert snap["last_error"] == "None"
        assert "2026-09-28" in snap["last_success"]
        assert "off" not in format_status_line()
        config.save({"theme": "dark", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": False})
        assert format_status_line().startswith("Always-on folder: off")
        assert activity_snapshot()["worker"] == "Off"
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=400)
        config.save_sync_status({"state": "idle", "last_finished": old.isoformat(), "message": ""})
        assert due_for_pass()
        recent = dt.datetime.now(dt.timezone.utc)
        config.save_sync_status({"state": "idle", "last_finished": recent.isoformat(), "message": ""})
        assert not due_for_pass()
        config.save_sync_status(
            {
                "state": "error",
                "last_finished": recent.isoformat(),
                "last_error": "upload secret.txt: HTTP 422",
                "last_pull": 0,
                "last_push": 1,
            }
        )
        config.save({"theme": "dark", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": True})
        err_snap = activity_snapshot()
        assert err_snap["last_error"] == "upload secret.txt: HTTP 422"
        assert "422" in format_status_line()
    finally:
        _restore_sync_config(original)


def test_lock_holder_pid(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-linux-sync-lock")
    folder.mkdir(parents=True, exist_ok=True)
    original = _isolate_sync_config(folder)
    holder: subprocess.Popen | None = None
    try:
        assert lock_holder_pid() == 0
        lock_path = folder / "sync.lock"
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl, os, time\n"
                    f"handle = open({str(lock_path)!r}, 'w', encoding='utf-8')\n"
                    "fcntl.flock(handle.fileno(), fcntl.LOCK_EX)\n"
                    "handle.write(str(os.getpid()))\n"
                    "handle.flush()\n"
                    "time.sleep(30)\n"
                ),
            ]
        )
        deadline = time.time() + 5
        pid = 0
        while time.time() < deadline:
            pid = lock_holder_pid()
            if pid == holder.pid:
                break
            time.sleep(0.05)
        assert pid == holder.pid, (pid, holder.pid, lock_path.read_text(encoding="utf-8") if lock_path.is_file() else None)
        config.save({"theme": "dark", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": True})
        snap = activity_snapshot()
        assert snap["worker"] == f"Running (pid {holder.pid})"
        assert snap["running"] is True
        holder.terminate()
        holder.wait(timeout=5)
        holder = None
        assert lock_holder_pid() == 0
        assert activity_snapshot()["worker"] == "Stopped"
    finally:
        if holder is not None and holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=5)
        _restore_sync_config(original)


def test_settings_always_on_wording() -> None:
    text = (ROOT / "proton_drive_linux" / "app.py").read_text(encoding="utf-8")
    assert '_("Always-on folder")' in text
    assert '_("Enable always-on folder")' in text
    assert '_("Worker")' in text
    assert '_("Last successful pass")' in text
    assert '_("Files last pass")' in text
    assert '_("Last error")' in text
    assert "Keep a local My files folder" not in text
    assert "_set_autostart(True)" in text
    assert "start_sync_now()" in text
    assert "activity_snapshot()" in text


def test_live_sync_primitives() -> None:
    cli = ProtonDriveCli()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    remote_name = f"pdl-sync-{stamp}"
    local_root = Path(f"/tmp/proton-drive-linux-sync-{stamp}")
    push_dir = local_root / "push"
    pull_dir = local_root / "pull"
    push_dir.mkdir(parents=True, exist_ok=True)
    pull_dir.mkdir(parents=True, exist_ok=True)
    sample = push_dir / "hello.txt"
    sample.write_text(f"sync-folder probe {stamp}\n", encoding="utf-8")
    created = [remote_name]
    try:
        cli.mkdir("/my-files", remote_name)
        remote = join_path("/my-files", remote_name)
        cli.upload([str(sample)], remote)
        names = {node_name(n) for n in cli.list(remote)}
        assert "hello.txt" in names
        cli.download(join_path(remote, "hello.txt"), str(pull_dir))
        pulled = pull_dir / "hello.txt"
        assert pulled.is_file(), list(pull_dir.iterdir())
        assert stamp in pulled.read_text(encoding="utf-8")
        print("sync primitives ok", remote)
    finally:
        try:
            live = cli.list("/my-files")
        except CliError:
            live = []
        for node in live:
            name = node_name(node)
            if name in created or name.startswith(f"pdl-sync-{stamp}"):
                try:
                    cli.trash(join_path("/my-files", name))
                except CliError:
                    pass
        try:
            trash_nodes = cli.list("/trash")
        except CliError:
            trash_nodes = []
        for node in trash_nodes:
            name = node_name(node)
            if name in created or name.startswith(f"pdl-sync-{stamp}"):
                try:
                    cli.delete(join_path("/trash", name))
                except CliError:
                    pass


if __name__ == "__main__":
    test_official_cli_has_no_fuse()
    test_local_children_skips_hidden()
    test_parse_sync_status()
    test_status_helpers()
    test_lock_holder_pid()
    test_settings_always_on_wording()
    test_live_sync_primitives()
    print("sync checks passed")
