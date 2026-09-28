#!/usr/bin/env python3
"""Sync-folder worker checks. Full /my-files mirror is not run here."""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_linux import config  # noqa: E402
from proton_drive_linux.cli import CliError, ProtonDriveCli, find_binary, join_path, node_name  # noqa: E402
from proton_drive_linux.sync import due_for_pass, format_status_line, local_children  # noqa: E402


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


def test_status_helpers(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-linux-sync-status")
    folder.mkdir(parents=True, exist_ok=True)
    original = (config.CONFIG_DIR, config.CONFIG_PATH, config.SYNC_STATUS_PATH)
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    config.SYNC_STATUS_PATH = folder / "sync-status.json"
    try:
        config.save({"theme": "dark", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": True})
        assert "off" not in format_status_line()
        config.save({"theme": "dark", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": False})
        assert format_status_line().startswith("Sync folder: off")
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=400)
        config.save_sync_status({"state": "idle", "last_finished": old.isoformat(), "message": ""})
        assert due_for_pass()
        recent = dt.datetime.now(dt.timezone.utc)
        config.save_sync_status({"state": "idle", "last_finished": recent.isoformat(), "message": ""})
        assert not due_for_pass()
    finally:
        config.CONFIG_DIR, config.CONFIG_PATH, config.SYNC_STATUS_PATH = original


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
    test_status_helpers()
    test_live_sync_primitives()
    print("sync checks passed")
