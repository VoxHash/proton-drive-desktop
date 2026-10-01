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

from proton_drive_desktop import config  # noqa: E402
from proton_drive_desktop.cli import CliError, ProtonDriveCli, find_binary, join_path, node_name  # noqa: E402
from proton_drive_desktop.config import parse_sync_status  # noqa: E402
from proton_drive_desktop.sync import (  # noqa: E402
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
    folder = tmp_path or Path("/tmp/proton-drive-desktop-sync-children")
    folder.mkdir(parents=True, exist_ok=True)
    visible = folder / "notes.txt"
    hidden = folder / ".hidden"
    visible.write_text("ok", encoding="utf-8")
    hidden.write_text("no", encoding="utf-8")
    names = [path.name for path in local_children(folder)]
    assert names == ["notes.txt"]
    visible.unlink()
    hidden.unlink()


def test_exclude_patterns() -> None:
    from proton_drive_desktop.sync import is_excluded, parse_exclude_patterns

    rules = parse_exclude_patterns("*.tmp\n# comment\nnode_modules, !keep.tmp")
    assert rules == [(False, "*.tmp"), (False, "node_modules"), (True, "keep.tmp")]
    assert is_excluded("cache.tmp", rules) is True
    assert is_excluded("keep.tmp", rules) is False  # last matching ! wins
    assert is_excluded("notes.txt", rules) is False
    assert is_excluded("node_modules", rules) is True
    assert parse_exclude_patterns("") == []
    assert parse_exclude_patterns(["*.log", "!important.log"]) == [
        (False, "*.log"),
        (True, "important.log"),
    ]
    assert is_excluded("foo/", parse_exclude_patterns("foo/")) is True
    print("exclude patterns ok")


def test_sync_remote_root() -> None:
    from proton_drive_desktop.config import normalize_sync_remote_root
    from proton_drive_desktop.sync import configured_remote_root

    assert normalize_sync_remote_root("/my-files") == "/my-files"
    assert normalize_sync_remote_root("/my-files/Work/") == "/my-files/Work"
    assert normalize_sync_remote_root("my-files/Docs") == "/my-files/Docs"
    assert normalize_sync_remote_root("/photos") == "/my-files"
    assert normalize_sync_remote_root("/trash") == "/my-files"
    assert normalize_sync_remote_root("") == "/my-files"
    assert configured_remote_root({"sync_remote_root": "/my-files/Archive"}) == "/my-files/Archive"
    assert configured_remote_root({"sync_remote_root": "/shared-with-me"}) == "/my-files"
    print("sync remote root ok")


def test_sync_conflict_policy() -> None:
    from proton_drive_desktop.config import normalize_sync_conflict_policy
    from proton_drive_desktop.sync import configured_conflict_flags, conflict_cli_flags

    assert normalize_sync_conflict_policy(None) == "skip"
    assert normalize_sync_conflict_policy("") == "skip"
    assert normalize_sync_conflict_policy("SKIP") == "skip"
    assert normalize_sync_conflict_policy("rename") == "rename"
    assert normalize_sync_conflict_policy("Rename") == "rename"
    assert normalize_sync_conflict_policy("replace") == "skip"
    assert normalize_sync_conflict_policy("remove") == "skip"
    assert conflict_cli_flags("skip") == ("skip", "merge")
    assert conflict_cli_flags(None) == ("skip", "merge")
    assert conflict_cli_flags("rename") == ("rename", "merge")
    assert conflict_cli_flags("bogus") == ("skip", "merge")
    assert configured_conflict_flags({"sync_conflict_policy": "rename"}) == ("rename", "merge")
    assert configured_conflict_flags({}) == ("skip", "merge")
    print("sync conflict policy ok")


def test_sync_direction() -> None:
    from proton_drive_desktop.config import SYNC_DIRECTIONS, normalize_sync_direction
    from proton_drive_desktop.sync import (
        configured_sync_direction,
        direction_allows_download,
        direction_allows_upload,
    )

    assert SYNC_DIRECTIONS == ("bidirectional", "upload-only", "download-only")
    assert normalize_sync_direction(None) == "bidirectional"
    assert normalize_sync_direction("") == "bidirectional"
    assert normalize_sync_direction("bogus") == "bidirectional"
    assert normalize_sync_direction("BIDIRECTIONAL") == "bidirectional"
    assert normalize_sync_direction("two_way") == "bidirectional"
    assert normalize_sync_direction("upload-only") == "upload-only"
    assert normalize_sync_direction("upload_only") == "upload-only"
    assert normalize_sync_direction("upload") == "upload-only"
    assert normalize_sync_direction("download-only") == "download-only"
    assert normalize_sync_direction("download") == "download-only"
    assert configured_sync_direction({}) == "bidirectional"
    assert configured_sync_direction({"sync_direction": "upload-only"}) == "upload-only"
    assert direction_allows_download("bidirectional") is True
    assert direction_allows_upload("bidirectional") is True
    assert direction_allows_download("upload-only") is False
    assert direction_allows_upload("upload-only") is True
    assert direction_allows_download("download-only") is True
    assert direction_allows_upload("download-only") is False
    print("sync direction ok")


def test_sync_interval_seconds() -> None:
    from proton_drive_desktop.config import (
        SYNC_INTERVAL_SECONDS_DEFAULT,
        SYNC_INTERVAL_SECONDS_MAX,
        SYNC_INTERVAL_SECONDS_MIN,
        normalize_sync_interval_seconds,
    )
    from proton_drive_desktop.sync import INTERVAL_SECONDS, configured_interval_seconds

    assert INTERVAL_SECONDS == SYNC_INTERVAL_SECONDS_DEFAULT == 300
    assert SYNC_INTERVAL_SECONDS_MIN == 60
    assert SYNC_INTERVAL_SECONDS_MAX == 86400
    assert normalize_sync_interval_seconds(None) == 300
    assert normalize_sync_interval_seconds("") == 300
    assert normalize_sync_interval_seconds("bogus") == 300
    assert normalize_sync_interval_seconds(120) == 120
    assert normalize_sync_interval_seconds("180") == 180
    assert normalize_sync_interval_seconds(30) == 60
    assert normalize_sync_interval_seconds(0) == 60
    assert normalize_sync_interval_seconds(-5) == 60
    assert normalize_sync_interval_seconds(999999) == 86400
    assert configured_interval_seconds({"sync_interval_seconds": 120}) == 120
    assert configured_interval_seconds({}) == 300
    mid = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=150)
    status = {"state": "idle", "last_finished": mid.isoformat(), "message": ""}
    assert not due_for_pass(status, interval_seconds=300)
    assert due_for_pass(status, interval_seconds=120)
    assert not due_for_pass(status, cfg={"sync_interval_seconds": 300})
    assert due_for_pass(status, cfg={"sync_interval_seconds": 60})
    print("sync interval seconds ok")


def test_sync_pass_timeout_seconds() -> None:
    from proton_drive_desktop.config import (
        SYNC_PASS_TIMEOUT_SECONDS_DEFAULT,
        SYNC_PASS_TIMEOUT_SECONDS_MAX,
        SYNC_PASS_TIMEOUT_SECONDS_MIN,
        SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED,
        normalize_sync_pass_timeout_seconds,
    )
    from proton_drive_desktop.sync import (
        PassTimedOut,
        PassWatchdog,
        configured_pass_timeout_seconds,
        is_transient_cli_error,
    )

    assert SYNC_PASS_TIMEOUT_SECONDS_DEFAULT == 0
    assert SYNC_PASS_TIMEOUT_SECONDS_MIN == 60
    assert SYNC_PASS_TIMEOUT_SECONDS_MAX == 86400
    assert SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED == 3600
    assert normalize_sync_pass_timeout_seconds(None) == 0
    assert normalize_sync_pass_timeout_seconds("") == 0
    assert normalize_sync_pass_timeout_seconds("bogus") == 0
    assert normalize_sync_pass_timeout_seconds(0) == 0
    assert normalize_sync_pass_timeout_seconds(-5) == 0
    assert normalize_sync_pass_timeout_seconds(False) == 0
    assert normalize_sync_pass_timeout_seconds(30) == 60
    assert normalize_sync_pass_timeout_seconds(120) == 120
    assert normalize_sync_pass_timeout_seconds("180") == 180
    assert normalize_sync_pass_timeout_seconds(999999) == 86400
    assert configured_pass_timeout_seconds({"sync_pass_timeout_seconds": 0}) == 0
    assert configured_pass_timeout_seconds({"sync_pass_timeout_seconds": 3600}) == 3600
    assert configured_pass_timeout_seconds({}) == 0
    assert is_transient_cli_error(PassTimedOut("Sync pass timed out after 60s")) is False

    fired: list[int] = []
    watchdog = PassWatchdog(0.2, lambda: fired.append(1))
    watchdog.start()
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)
    while not watchdog.timed_out() and dt.datetime.now(dt.timezone.utc) < deadline:
        time.sleep(0.05)
    watchdog.stop()
    assert fired == [1]
    assert watchdog.timed_out()
    try:
        watchdog.check()
        raise AssertionError("expected PassTimedOut")
    except PassTimedOut as exc:
        assert "timed out" in str(exc).lower()

    idle = PassWatchdog(0, lambda: fired.append(99))
    idle.start()
    time.sleep(0.05)
    idle.stop()
    assert fired == [1]
    assert not idle.timed_out()
    print("sync pass timeout seconds ok")


def test_upload_download_conflict_args() -> None:
    """Offline: upload/download pass real CLI -f/-d strategies into run_transfer."""

    class CaptureTransfer(ProtonDriveCli):
        def __init__(self) -> None:
            self.binary = "proton-drive"
            self.transfer_calls: list[list[str]] = []

        def run_transfer(  # type: ignore[override]
            self,
            args: list[str],
            *,
            timeout: int = 3600,
            on_progress=None,
        ) -> None:
            self.transfer_calls.append(list(args))

    cli = CaptureTransfer()
    cli.upload(["/tmp/a.txt"], "/my-files")
    cli.download("/my-files/a.txt", "/tmp/out")
    cli.upload(["/tmp/b.txt"], "/my-files", file_conflict="rename", folder_conflict="merge")
    cli.download(
        "/my-files/b.txt",
        "/tmp/out",
        file_conflict="rename",
        folder_conflict="merge",
    )
    assert cli.transfer_calls == [
        ["filesystem", "upload", "/tmp/a.txt", "/my-files", "-f", "skip", "-d", "merge", "-t"],
        ["filesystem", "download", "/my-files/a.txt", "/tmp/out", "-f", "skip", "-d", "merge"],
        ["filesystem", "upload", "/tmp/b.txt", "/my-files", "-f", "rename", "-d", "merge", "-t"],
        ["filesystem", "download", "/my-files/b.txt", "/tmp/out", "-f", "rename", "-d", "merge"],
    ]
    print("upload/download conflict args ok")


def _isolate_sync_config(folder: Path):
    original = (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.SYNC_DELTA_PATH,
        config.SYNC_LOCK_PATH,
        config.GUI_BUSY_PATH,
    )
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    config.SYNC_STATUS_PATH = folder / "sync-status.json"
    config.SYNC_DELTA_PATH = folder / "sync-delta.json"
    config.SYNC_LOCK_PATH = folder / "sync.lock"
    config.GUI_BUSY_PATH = folder / "gui-busy"
    return original


def _restore_sync_config(original) -> None:
    (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.SYNC_DELTA_PATH,
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
    folder = tmp_path or Path("/tmp/proton-drive-desktop-sync-status")
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
    folder = tmp_path or Path("/tmp/proton-drive-desktop-sync-lock")
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


def test_preview_pass_counts(tmp_path: Path | None = None) -> None:
    """Offline dry-run: real list counts via a fake CLI; no download/upload/delete."""
    folder = tmp_path or Path("/tmp/proton-drive-desktop-sync-preview")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.txt").write_text("local", encoding="utf-8")
    (folder / "skip.tmp").write_text("tmp", encoding="utf-8")
    (folder / ".hidden").write_text("no", encoding="utf-8")

    class FakeCli:
        def __init__(self) -> None:
            self.listed: list[str] = []
            self.downloads: list[tuple[str, str]] = []
            self.uploads: list[tuple[list[str], str]] = []
            self.deletes: list[str] = []

        def list(self, path: str) -> list[dict]:
            self.listed.append(path)
            return [
                {"name": "remote-a.txt"},
                {"name": "skip.tmp"},
                {"name": "remote-b.md"},
            ]

        def download(self, remote: str, dest: str) -> None:
            self.downloads.append((remote, dest))
            raise AssertionError("preview must not download")

        def upload(self, sources: list[str], remote: str) -> None:
            self.uploads.append((sources, remote))
            raise AssertionError("preview must not upload")

        def trash(self, path: str) -> None:
            self.deletes.append(path)
            raise AssertionError("preview must not trash")

        def delete(self, path: str) -> None:
            self.deletes.append(path)
            raise AssertionError("preview must not delete")

    from proton_drive_desktop.sync import format_preview_message, preview_pass

    cli = FakeCli()
    preview = preview_pass(
        cfg={
            "sync_folder": str(folder),
            "sync_remote_root": "/my-files/Work",
            "sync_exclude": "*.tmp",
            "sync_direction": "bidirectional",
        },
        cli=cli,  # type: ignore[arg-type]
    )
    assert cli.listed == ["/my-files/Work"]
    assert cli.downloads == []
    assert cli.uploads == []
    assert cli.deletes == []
    assert preview["destructive_deletes"] == 0
    assert preview["sync_direction"] == "bidirectional"
    assert preview["download_count"] == 2
    assert preview["upload_count"] == 1
    assert preview["download_names"] == ["remote-a.txt", "remote-b.md"]
    assert preview["upload_names"] == ["notes.txt"]
    assert preview["remote_root"] == "/my-files/Work"
    assert preview["folder"] == str(folder)
    message = format_preview_message(preview)
    assert "Would download 2 remote items" in message
    assert "Would upload 1 local item" in message
    assert "bidirectional" in message.lower()
    assert "never deletes" in message.lower() or "never delete" in message.lower()

    cli_up = FakeCli()
    upload_only = preview_pass(
        cfg={
            "sync_folder": str(folder),
            "sync_remote_root": "/my-files/Work",
            "sync_exclude": "*.tmp",
            "sync_direction": "upload-only",
        },
        cli=cli_up,  # type: ignore[arg-type]
    )
    assert cli_up.listed == []
    assert upload_only["download_count"] == 0
    assert upload_only["upload_count"] == 1
    assert upload_only["upload_names"] == ["notes.txt"]
    up_msg = format_preview_message(upload_only)
    assert "Would upload 1 local item" in up_msg
    assert "Would download" not in up_msg
    assert "upload only" in up_msg.lower()

    cli_down = FakeCli()
    download_only = preview_pass(
        cfg={
            "sync_folder": str(folder),
            "sync_remote_root": "/my-files/Work",
            "sync_exclude": "*.tmp",
            "sync_direction": "download-only",
        },
        cli=cli_down,  # type: ignore[arg-type]
    )
    assert cli_down.listed == ["/my-files/Work"]
    assert download_only["download_count"] == 2
    assert download_only["upload_count"] == 0
    assert download_only["upload_names"] == []
    down_msg = format_preview_message(download_only)
    assert "Would download 2 remote items" in down_msg
    assert "Would upload" not in down_msg
    assert "download only" in down_msg.lower()
    print("preview pass ok")


def test_seed_sync_delta_skips_bulk(tmp_path: Path | None = None) -> None:
    """Offline: seed records real list fingerprints; next run_once transfers nothing."""
    from proton_drive_desktop import sync as sync_mod
    from proton_drive_desktop.config import load_sync_delta

    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-seed")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    sync_dir = root / "sync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sync_dir.mkdir(parents=True, exist_ok=True)
    local_file = sync_dir / "notes.txt"
    local_file.write_text("hello", encoding="utf-8")
    original = _isolate_sync_config(cfg_dir)

    class FakeCli:
        def __init__(self) -> None:
            self.listed: list[str] = []
            self.downloads: list[str] = []
            self.uploads: list[str] = []
            self.remote_nodes = [
                {
                    "name": "notes.txt",
                    "type": "file",
                    "modificationTime": "2026-09-29T12:00:00.000Z",
                    "activeRevision": {"claimedSize": 5},
                },
                {
                    "name": "remote-only.txt",
                    "type": "file",
                    "modificationTime": "2026-09-29T13:00:00.000Z",
                    "activeRevision": {"claimedSize": 3},
                },
            ]

        def list(self, path: str) -> list[dict]:
            self.listed.append(path)
            return list(self.remote_nodes)

        def download(self, remote: str, dest: str, **_kwargs) -> None:
            self.downloads.append(remote)

        def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
            self.uploads.extend(sources)

    previous = sync_mod.ProtonDriveCli
    try:
        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files/Work",
                "sync_direction": "bidirectional",
            }
        )
        seed_cli = FakeCli()
        result = sync_mod.seed_sync_delta(
            cfg=config.load(),
            cli=seed_cli,  # type: ignore[arg-type]
        )
        assert seed_cli.listed == ["/my-files/Work"]
        assert seed_cli.downloads == []
        assert seed_cli.uploads == []
        assert result["item_count"] == 2
        assert result["remote_seeded"] == 2
        assert result["local_seeded"] == 1
        delta = load_sync_delta()
        assert "notes.txt" in delta["items"]
        assert "remote-only.txt" in delta["items"]
        assert delta["items"]["notes.txt"].get("local_size") == 5
        assert delta["items"]["notes.txt"].get("remote_mtime")
        msg = sync_mod.format_seed_message(result)
        assert "2" in msg and "already synced" in msg.lower()

        fake = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake  # type: ignore[assignment, return-value]
        status = sync_mod.run_once(force=True)
        assert status["state"] == "idle"
        assert status["last_pull"] == 0
        assert status["last_push"] == 0
        assert fake.downloads == []
        assert fake.uploads == []
        assert "skipped" in str(status.get("message") or "").lower()

        # Local edit after seed must still upload.
        local_file.write_text("hello!", encoding="utf-8")
        fake2 = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake2  # type: ignore[assignment, return-value]
        after = sync_mod.run_once(force=True)
        assert after["last_push"] == 1
        assert any(path.endswith("notes.txt") for path in fake2.uploads)
    finally:
        sync_mod.ProtonDriveCli = previous
        _restore_sync_config(original)
    print("seed sync delta ok")


def test_local_delta_tracking(tmp_path: Path | None = None) -> None:
    """Offline: second pass skips unchanged top-level children; scope reset on path change."""
    from proton_drive_desktop import sync as sync_mod
    from proton_drive_desktop.config import load_sync_delta, save_sync_delta

    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-delta")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    sync_dir = root / "sync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sync_dir.mkdir(parents=True, exist_ok=True)
    local_file = sync_dir / "notes.txt"
    local_file.write_text("hello", encoding="utf-8")
    original = _isolate_sync_config(cfg_dir)

    class FakeCli:
        def __init__(self) -> None:
            self.listed: list[str] = []
            self.downloads: list[str] = []
            self.uploads: list[str] = []
            self.remote_nodes = [
                {
                    "name": "notes.txt",
                    "type": "file",
                    "modificationTime": "2026-09-29T12:00:00.000Z",
                    "activeRevision": {"claimedSize": 5},
                },
                {
                    "name": "remote-only.txt",
                    "type": "file",
                    "modificationTime": "2026-09-29T13:00:00.000Z",
                    "activeRevision": {"claimedSize": 3},
                },
            ]

        def list(self, path: str) -> list[dict]:
            self.listed.append(path)
            return list(self.remote_nodes)

        def download(self, remote: str, dest: str, **_kwargs) -> None:
            self.downloads.append(remote)
            name = Path(remote).name
            if name == "remote-only.txt":
                Path(dest).joinpath(name).write_text("hi", encoding="utf-8")

        def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
            self.uploads.extend(sources)

    previous = sync_mod.ProtonDriveCli
    try:
        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files/Work",
                "sync_direction": "bidirectional",
            }
        )
        fake1 = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake1  # type: ignore[assignment, return-value]
        first = sync_mod.run_once(force=True)
        assert first["state"] == "idle"
        assert first["last_pull"] == 2
        # notes.txt downloaded then upload skipped (local fp recorded after download)
        assert "/my-files/Work/notes.txt" in fake1.downloads
        assert "/my-files/Work/remote-only.txt" in fake1.downloads
        assert fake1.uploads == []
        delta = load_sync_delta()
        assert delta["folder"] == str(sync_dir)
        assert delta["remote_root"] == "/my-files/Work"
        assert "notes.txt" in delta["items"]
        assert "remote-only.txt" in delta["items"]

        fake2 = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake2  # type: ignore[assignment, return-value]
        second = sync_mod.run_once(force=True)
        assert second["state"] == "idle"
        assert second["last_pull"] == 0
        assert second["last_push"] == 0
        assert fake2.downloads == []
        assert fake2.uploads == []
        assert "skipped" in str(second.get("message") or "").lower()

        # Local edit must upload again
        local_file.write_text("hello!", encoding="utf-8")
        fake3 = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake3  # type: ignore[assignment, return-value]
        third = sync_mod.run_once(force=True)
        assert third["last_push"] == 1
        assert any(path.endswith("notes.txt") for path in fake3.uploads)
        # Unchanged remote-only still skipped on download
        assert fake3.downloads == []

        # Remote root change invalidates delta scope
        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files/Other",
                "sync_direction": "bidirectional",
            }
        )
        fake4 = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake4  # type: ignore[assignment, return-value]
        fourth = sync_mod.run_once(force=True)
        assert fourth["last_pull"] == 2
        assert fake4.listed == ["/my-files/Other"]
        assert len(fake4.downloads) == 2

        # Fingerprint helpers / scope reset unit checks
        fp = sync_mod.local_fingerprint(local_file)
        assert fp is not None
        assert fp["local_size"] == len("hello!")
        assert fp["local_is_dir"] is False
        scoped = sync_mod.ensure_sync_delta_scope(
            {"version": 1, "folder": str(sync_dir), "remote_root": "/my-files/Other", "direction": "bidirectional", "items": {"x": {}}},
            folder=sync_dir,
            remote_root="/my-files/Other",
            direction="upload-only",
        )
        assert scoped["items"] == {}
        assert scoped["direction"] == "upload-only"
        save_sync_delta(scoped)
        assert load_sync_delta()["direction"] == "upload-only"
    finally:
        sync_mod.ProtonDriveCli = previous
        _restore_sync_config(original)
    print("local delta tracking ok")


def test_run_once_respects_direction(tmp_path: Path | None = None) -> None:
    """Offline: worker skips the disallowed half for upload-only / download-only."""
    from proton_drive_desktop import sync as sync_mod

    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-direction")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    sync_dir = root / "sync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / "local.txt").write_text("local", encoding="utf-8")
    original = _isolate_sync_config(cfg_dir)

    class FakeCli:
        def __init__(self) -> None:
            self.listed: list[str] = []
            self.downloads: list[str] = []
            self.uploads: list[str] = []

        def list(self, path: str) -> list[dict]:
            self.listed.append(path)
            return [{"name": "remote.txt"}]

        def download(self, remote: str, dest: str, **_kwargs) -> None:
            self.downloads.append(remote)

        def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
            self.uploads.extend(sources)

    previous = sync_mod.ProtonDriveCli
    try:
        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files",
                "sync_direction": "upload-only",
            }
        )
        fake_up = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake_up  # type: ignore[assignment, return-value]
        result_up = sync_mod.run_once(force=True)
        assert result_up["state"] == "idle"
        assert fake_up.listed == []
        assert fake_up.downloads == []
        assert len(fake_up.uploads) == 1
        assert fake_up.uploads[0].endswith("local.txt")

        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files",
                "sync_direction": "download-only",
            }
        )
        fake_down = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake_down  # type: ignore[assignment, return-value]
        result_down = sync_mod.run_once(force=True)
        assert result_down["state"] == "idle"
        assert fake_down.listed == ["/my-files"]
        assert fake_down.downloads == ["/my-files/remote.txt"]
        assert fake_down.uploads == []
    finally:
        sync_mod.ProtonDriveCli = previous
        _restore_sync_config(original)
    print("run_once direction ok")


def test_sync_retry_backoff() -> None:
    """Offline: transient retries with backoff; auth never retried; idempotent ops succeed."""
    from proton_drive_desktop.cli import CliError, NotLoggedIn, TransferCancelled
    from proton_drive_desktop.sync import (
        SYNC_RETRY_ATTEMPTS,
        SYNC_RETRY_BACKOFF_SECONDS,
        IdempotentResult,
        call_with_retry,
        is_already_exists_error,
        is_already_gone_error,
        is_idempotent_cli_success,
        is_transient_cli_error,
    )

    assert SYNC_RETRY_ATTEMPTS == 3
    assert SYNC_RETRY_BACKOFF_SECONDS == (1.0, 2.0, 4.0)

    assert is_transient_cli_error("Operation failed: Please retry (Code=200501, Status=422)")
    assert is_transient_cli_error(CliError("502 Bad Gateway"))
    assert is_transient_cli_error("connection reset by peer")
    assert is_transient_cli_error("proton-drive transfer timed out")
    assert not is_transient_cli_error(NotLoggedIn("You need to login"))
    assert not is_transient_cli_error(CliError("You need to login"))
    assert not is_transient_cli_error(TransferCancelled("Transfer cancelled"))
    assert not is_transient_cli_error(CliError("A file or folder with that name already exists (Code=2500)"))

    assert is_already_gone_error("Node not found")
    assert is_already_gone_error("File or folder not found (Code=2501, Status=422)")
    assert is_already_exists_error("A file or folder with that name already exists (Code=2500)")
    assert is_idempotent_cli_success("trash", "Node not found")
    assert is_idempotent_cli_success("create-folder", "already exists")
    assert is_idempotent_cli_success("upload", "name already exists")
    assert is_idempotent_cli_success("download", "File or folder not found")
    assert not is_idempotent_cli_success("list", "Node not found")

    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise CliError("502 Bad Gateway")
        return "ok"

    assert call_with_retry(flaky, op="upload", sleep=sleeps.append) == "ok"
    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]

    auth_calls = {"n": 0}

    def auth_fail() -> None:
        auth_calls["n"] += 1
        raise CliError("Error: You need to login")

    try:
        call_with_retry(auth_fail, op="upload", sleep=sleeps.append)
        raise AssertionError("expected NotLoggedIn")
    except NotLoggedIn:
        pass
    assert auth_calls["n"] == 1

    def already_exists() -> None:
        raise CliError("A file or folder with that name already exists (Code=2500, Status=422)")

    done = call_with_retry(already_exists, op="create-folder", sleep=sleeps.append)
    assert isinstance(done, IdempotentResult)
    assert done.reason == "already_exists"

    gone = call_with_retry(
        lambda: (_ for _ in ()).throw(CliError("Node not found")),
        op="trash",
        sleep=sleeps.append,
    )
    assert isinstance(gone, IdempotentResult)
    assert gone.reason == "already_gone"

    permanent_calls = {"n": 0}

    def permanent() -> None:
        permanent_calls["n"] += 1
        raise CliError("permission denied")

    try:
        call_with_retry(permanent, op="upload", sleep=sleeps.append)
        raise AssertionError("expected CliError")
    except CliError as exc:
        assert "permission denied" in str(exc)
    assert permanent_calls["n"] == 1
    print("sync retry backoff ok")


def test_run_once_pass_timeout(tmp_path: Path | None = None) -> None:
    """Offline: per-pass watchdog cancels a hung CLI upload and ends the pass."""
    from proton_drive_desktop import sync as sync_mod
    from proton_drive_desktop.cli import TransferCancelled

    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-pass-timeout")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    sync_dir = root / "sync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / "stuck.txt").write_text("hang", encoding="utf-8")
    original = _isolate_sync_config(cfg_dir)
    previous = sync_mod.ProtonDriveCli
    try:
        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files",
                "sync_direction": "upload-only",
                "sync_pass_timeout_seconds": 60,
            }
        )

        class HungUpload:
            def __init__(self) -> None:
                self.cancelled = False
                self.cancel_calls = 0
                self.uploads = 0

            def cancel_transfer(self) -> bool:
                self.cancel_calls += 1
                self.cancelled = True
                return True

            def list(self, path: str) -> list[dict]:
                return []

            def download(self, remote: str, dest: str, **_kwargs) -> None:
                raise AssertionError("upload-only must not download")

            def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
                self.uploads += 1
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if self.cancelled:
                        raise TransferCancelled("Transfer cancelled")
                    time.sleep(0.02)
                raise AssertionError("watchdog did not cancel hung upload")

        hung = HungUpload()
        sync_mod.ProtonDriveCli = lambda: hung  # type: ignore[assignment, return-value]

        class FastWatchdog(sync_mod.PassWatchdog):
            def __init__(self, seconds, on_fire=None, *, message: str = "") -> None:
                super().__init__(0.15 if float(seconds or 0) > 0 else 0, on_fire, message=message)

        previous_watchdog = sync_mod.PassWatchdog
        sync_mod.PassWatchdog = FastWatchdog  # type: ignore[assignment, misc]
        try:
            result = sync_mod.run_once(force=True)
        finally:
            sync_mod.PassWatchdog = previous_watchdog
        assert result["state"] == "error"
        assert "timed out" in str(result.get("last_error") or "").lower()
        assert hung.cancel_calls >= 1
        assert hung.uploads >= 1
    finally:
        sync_mod.ProtonDriveCli = previous
        _restore_sync_config(original)
    print("run_once pass timeout ok")


def test_run_once_retries_transient(tmp_path: Path | None = None) -> None:
    """Offline: run_once retries a transient upload then succeeds; auth aborts the pass."""
    from proton_drive_desktop import sync as sync_mod
    from proton_drive_desktop.cli import CliError, NotLoggedIn

    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-retry")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    sync_dir = root / "sync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / "notes.txt").write_text("retry-me", encoding="utf-8")
    original = _isolate_sync_config(cfg_dir)
    previous = sync_mod.ProtonDriveCli
    real_sleep = sync_mod.time.sleep
    try:
        sync_mod.time.sleep = lambda _seconds: None  # type: ignore[assignment]
        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files",
                "sync_direction": "upload-only",
            }
        )

        class FlakyUpload:
            def __init__(self) -> None:
                self.uploads = 0

            def list(self, path: str) -> list[dict]:
                return []

            def download(self, remote: str, dest: str, **_kwargs) -> None:
                raise AssertionError("upload-only must not download")

            def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
                self.uploads += 1
                if self.uploads < 3:
                    raise CliError("Operation failed: Please retry (Code=200501, Status=422)")

        flaky = FlakyUpload()
        sync_mod.ProtonDriveCli = lambda: flaky  # type: ignore[assignment, return-value]
        result = sync_mod.run_once(force=True)
        assert result["state"] == "idle"
        assert result["last_push"] == 1
        assert flaky.uploads == 3

        class AuthFail:
            def list(self, path: str) -> list[dict]:
                raise NotLoggedIn("You need to login")

            def download(self, remote: str, dest: str, **_kwargs) -> None:
                raise AssertionError("should not reach download")

            def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
                raise NotLoggedIn("You need to login")

        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files",
                "sync_direction": "download-only",
            }
        )
        sync_mod.ProtonDriveCli = lambda: AuthFail()  # type: ignore[assignment, return-value]
        auth_result = sync_mod.run_once(force=True)
        assert auth_result["state"] == "error"
        assert "need to login" in str(auth_result.get("last_error") or "").lower()

        class ExistsUpload:
            def __init__(self) -> None:
                self.uploads = 0

            def list(self, path: str) -> list[dict]:
                return []

            def download(self, remote: str, dest: str, **_kwargs) -> None:
                raise AssertionError("upload-only must not download")

            def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
                self.uploads += 1
                raise CliError("A file or folder with that name already exists (Code=2500)")

        config.save(
            {
                "theme": "dark",
                "download_folder": str(sync_dir),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files",
                "sync_direction": "upload-only",
            }
        )
        # Touch local so delta does not skip the upload after the flaky pass.
        (sync_dir / "notes.txt").write_text("retry-me-again", encoding="utf-8")
        exists = ExistsUpload()
        sync_mod.ProtonDriveCli = lambda: exists  # type: ignore[assignment, return-value]
        skip_result = sync_mod.run_once(force=True)
        assert skip_result["state"] == "idle"
        assert skip_result["last_push"] == 1
        assert exists.uploads == 1
    finally:
        sync_mod.time.sleep = real_sleep
        sync_mod.ProtonDriveCli = previous
        _restore_sync_config(original)
    print("run_once retry ok")


def test_settings_always_on_wording() -> None:
    text = (ROOT / "proton_drive_desktop" / "app.py").read_text(encoding="utf-8")
    assert '_("Always-on folder")' in text
    assert '_("Enable always-on folder")' in text
    assert '_("Worker")' in text
    assert '_("Last successful pass")' in text
    assert '_("Files last pass")' in text
    assert '_("Last error")' in text
    assert '_("Exclude patterns")' in text
    assert '_("Remote root")' in text
    assert '_("Conflict policy")' in text
    assert '_("Skip existing files (merge folders)")' in text
    assert '_("Rename conflicting files (merge folders)")' in text
    assert "_on_sync_conflict_policy" in text
    assert '_("Sync direction")' in text
    assert '_("Bidirectional (download then upload)")' in text
    assert '_("Upload only (local → Drive)")' in text
    assert '_("Download only (Drive → local)")' in text
    assert "_on_sync_direction" in text
    assert '_("Sync interval (seconds)")' in text
    assert "_on_sync_interval" in text
    assert '_("Per-pass timeout")' in text
    assert '_("Pass timeout (seconds)")' in text
    assert "_on_sync_pass_timeout" in text
    assert "_on_sync_pass_timeout_enabled" in text
    assert "Adw.SpinRow.new_with_range" in text
    sync_text = (ROOT / "proton_drive_desktop" / "sync.py").read_text(encoding="utf-8")
    assert "configured_conflict_flags" in sync_text
    assert "configured_interval_seconds" in sync_text
    assert "configured_pass_timeout_seconds" in sync_text
    assert "PassWatchdog" in sync_text
    assert "configured_sync_direction" in sync_text
    assert "direction_allows_download" in sync_text
    assert "direction_allows_upload" in sync_text
    assert '_("Always-on folder preview")' in text
    assert "preview_pass" in text
    assert "should_skip_download" in sync_text
    assert "should_skip_upload" in sync_text
    assert "local_fingerprint" in sync_text
    assert "sync-delta.json" in (ROOT / "proton_drive_desktop" / "config.py").read_text(encoding="utf-8")
    assert "format_preview_message" in text
    assert "_run_sync_preview" in text
    assert "seed_sync_delta" in sync_text
    assert "format_seed_message" in text
    assert '_("Assume already synced")' in text
    assert "_on_sync_seed" in text
    assert "_seed_then_enable" in text
    assert "offer_seed" in text
    assert "Keep a local My files folder" not in text
    assert "_set_autostart(True)" in text
    assert "start_sync_now()" in text
    assert "activity_snapshot()" in text
    assert '_("systemd user timer")' in text
    assert "set_sync_systemd" in text
    assert "_on_systemd_sync" in text
    assert '_("Sync soon after local edits")' in text
    assert "set_sync_path_trigger" in text
    assert "_on_path_trigger" in text
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert (
        "- [x] Optional local path trigger (inotify or systemd path unit) to run a pass "
        "soon after edits under the always-on folder, not only on the fixed interval"
    ) in roadmap
    assert (
        "- [x] Seed / “assume already synced” on first enable (record current local+remote "
        "state and skip the initial bulk upload when the user says both sides already match)"
        in roadmap
        or '- [x] Seed / "assume already synced" on first enable (record current local+remote '
        "state and skip the initial bulk upload when the user says both sides already match)"
        in roadmap
    )
    assert (
        "- [x] Configurable sync interval in Settings (today fixed at 300s in `sync.py`)" in roadmap
    )
    assert (
        "- [x] Optional sync direction in Settings: bidirectional (default), upload-only, or "
        "download-only (one-way UP is what TrueNAS scripts need; desktop keeps two-way as default)"
        in roadmap
    )
    assert (
        "- [x] Retry with backoff for transient CLI / network failures during a sync pass "
        "(idempotent trash/create when the remote is already gone or already exists)"
        in roadmap
    )
    assert (
        "- [x] Optional per-pass timeout / watchdog so a hung CLI transfer cannot block "
        "the worker forever" in roadmap
    )
    assert "call_with_retry" in sync_text
    assert "is_transient_cli_error" in sync_text
    assert "is_idempotent_cli_success" in sync_text
    assert 'getattr(cli, "cancel_transfer"' in sync_text


def test_live_sync_primitives() -> None:
    cli = ProtonDriveCli()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    remote_name = f"pdl-sync-{stamp}"
    local_root = Path(f"/tmp/proton-drive-desktop-sync-{stamp}")
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


def _offline_mode() -> bool:
    flag = os.environ.get("PROTON_DRIVE_OFFLINE", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    if not _offline_mode():
        test_official_cli_has_no_fuse()
    else:
        print("offline mode: skipped official CLI binary probe")
    test_local_children_skips_hidden()
    test_exclude_patterns()
    test_sync_remote_root()
    test_sync_conflict_policy()
    test_sync_direction()
    test_sync_interval_seconds()
    test_sync_pass_timeout_seconds()
    test_upload_download_conflict_args()
    test_parse_sync_status()
    test_status_helpers()
    test_lock_holder_pid()
    test_preview_pass_counts()
    test_seed_sync_delta_skips_bulk()
    test_local_delta_tracking()
    test_run_once_respects_direction()
    test_sync_retry_backoff()
    test_run_once_pass_timeout()
    test_run_once_retries_transient()
    test_settings_always_on_wording()
    if _offline_mode():
        print("offline mode: skipped live sync primitives")
    else:
        test_live_sync_primitives()
    print("sync checks passed")
