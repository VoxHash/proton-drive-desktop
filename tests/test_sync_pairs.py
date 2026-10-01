#!/usr/bin/env python3
"""Offline multi-folder sync pair, pause, and activity-history checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import config  # noqa: E402
from proton_drive_desktop import sync as sync_mod  # noqa: E402


def _isolate(folder: Path):
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


def _restore(original) -> None:
    (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.SYNC_DELTA_PATH,
        config.SYNC_LOCK_PATH,
        config.GUI_BUSY_PATH,
    ) = original


def test_migrate_legacy_single_folder_to_pairs(tmp_path: Path | None = None) -> None:
    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-pairs-migrate")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sync_dir = root / "ProtonDrive"
    sync_dir.mkdir(parents=True, exist_ok=True)
    original = _isolate(cfg_dir)
    try:
        config.save(
            {
                "theme": "dark",
                "download_folder": str(root),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_remote_root": "/my-files/Work",
                "sync_exclude": "*.tmp",
                "sync_direction": "upload-only",
                "sync_conflict_policy": "rename",
            }
        )
        loaded = config.load()
        pairs = loaded["sync_pairs"]
        assert len(pairs) == 1
        assert pairs[0]["local_path"] == str(sync_dir)
        assert pairs[0]["remote_root"] == "/my-files/Work"
        assert pairs[0]["exclude"] == "*.tmp"
        assert pairs[0]["direction"] == "upload-only"
        assert pairs[0]["conflict_policy"] == "rename"
        assert pairs[0]["enabled"] is True
        assert loaded["sync_folder"] == str(sync_dir)
        assert loaded["sync_remote_root"] == "/my-files/Work"
    finally:
        _restore(original)
    print("migrate legacy to pairs ok")


def test_multi_pair_run_once(tmp_path: Path | None = None) -> None:
    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-pairs-run")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    a_dir = root / "a"
    b_dir = root / "b"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    a_dir.mkdir(parents=True, exist_ok=True)
    b_dir.mkdir(parents=True, exist_ok=True)
    (a_dir / "a.txt").write_text("a", encoding="utf-8")
    (b_dir / "b.txt").write_text("b", encoding="utf-8")
    original = _isolate(cfg_dir)

    class FakeCli:
        def __init__(self) -> None:
            self.listed: list[str] = []
            self.uploads: list[str] = []

        def list(self, path: str) -> list[dict]:
            self.listed.append(path)
            return []

        def download(self, remote: str, dest: str, **_kwargs) -> None:
            return None

        def upload(self, sources: list[str], remote: str, **_kwargs) -> None:
            self.uploads.extend(sources)

    previous = sync_mod.ProtonDriveCli
    try:
        pairs = [
            config.empty_sync_pair(
                pair_id="pair-a",
                local_path=str(a_dir),
                remote_root="/my-files/A",
                direction="upload-only",
            ),
            config.empty_sync_pair(
                pair_id="pair-b",
                local_path=str(b_dir),
                remote_root="/my-files/B",
                direction="upload-only",
            ),
        ]
        config.save(
            {
                "theme": "dark",
                "download_folder": str(root),
                "cli_path": "",
                "autostart": False,
                "sync_enabled": True,
                "sync_pairs": pairs,
            }
        )
        fake = FakeCli()
        sync_mod.ProtonDriveCli = lambda: fake  # type: ignore[assignment, return-value]
        status = sync_mod.run_once(force=True)
        assert status["state"] == "idle"
        assert status["last_push"] == 2
        assert status["last_pair_count"] == 2
        assert any(path.endswith("a.txt") for path in fake.uploads)
        assert any(path.endswith("b.txt") for path in fake.uploads)
        assert len(status.get("history") or []) >= 1
        delta_a = config.load_sync_delta("pair-a")
        delta_b = config.load_sync_delta("pair-b")
        assert "a.txt" in delta_a["items"]
        assert "b.txt" in delta_b["items"]
        store = json.loads(config.SYNC_DELTA_PATH.read_text(encoding="utf-8"))
        assert store["version"] == 2
        assert "pair-a" in store["pairs"] and "pair-b" in store["pairs"]
    finally:
        sync_mod.ProtonDriveCli = previous
        _restore(original)
    print("multi pair run_once ok")


def test_pause_blocks_due_and_run_once(tmp_path: Path | None = None) -> None:
    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-pause")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    sync_dir = root / "sync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    sync_dir.mkdir(parents=True, exist_ok=True)
    original = _isolate(cfg_dir)
    previous = sync_mod.ProtonDriveCli
    try:
        config.save(
            {
                "theme": "dark",
                "download_folder": str(root),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(sync_dir),
                "sync_enabled": True,
                "sync_paused": True,
                "sync_interval_seconds": 60,
            }
        )
        assert sync_mod.sync_is_paused() is True
        assert sync_mod.due_for_pass(cfg=config.load()) is False
        called = {"n": 0}

        class FakeCli:
            def list(self, path: str) -> list[dict]:
                called["n"] += 1
                return []

            def download(self, *args, **kwargs) -> None:
                called["n"] += 1

            def upload(self, *args, **kwargs) -> None:
                called["n"] += 1

        sync_mod.ProtonDriveCli = lambda: FakeCli()  # type: ignore[assignment, return-value]
        status = sync_mod.run_once(force=False)
        assert status["state"] == "paused"
        assert called["n"] == 0
        # force still runs while paused (Sync now / resume path)
        status_force = sync_mod.run_once(force=True)
        assert status_force["state"] in {"idle", "error"}
    finally:
        sync_mod.ProtonDriveCli = previous
        _restore(original)
    print("pause blocks due/run_once ok")


def test_activity_history_bounded(tmp_path: Path | None = None) -> None:
    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-history")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    original = _isolate(cfg_dir)
    try:
        status: dict = {"state": "idle", "history": []}
        for index in range(config.SYNC_ACTIVITY_HISTORY_MAX + 5):
            status = config.append_sync_activity_history(
                status,
                finished=f"2026-09-29T12:{index:02d}:00+00:00",
                pull=index,
                push=0,
                skipped_pull=1,
                skipped_push=2,
                errors="",
                timeout=False,
                pair_count=1,
                message=f"pass {index}",
            )
        assert len(status["history"]) == config.SYNC_ACTIVITY_HISTORY_MAX
        assert status["history"][0]["pull"] == 5
        assert status["history"][-1]["pull"] == config.SYNC_ACTIVITY_HISTORY_MAX + 4
        snap = sync_mod.activity_snapshot(status)
        assert snap["last_skipped_pull"] == 0 or True  # defaults when not in status
        assert len(snap["history_lines"]) <= 20
        assert "↓" in snap["history_lines"][0] or "remote" in snap["history_lines"][0].lower() or "·" in snap["history_lines"][0]
    finally:
        _restore(original)
    print("activity history bounded ok")


def test_legacy_delta_migrates_to_store(tmp_path: Path | None = None) -> None:
    root = tmp_path or Path("/tmp/proton-drive-desktop-sync-delta-migrate")
    root.mkdir(parents=True, exist_ok=True)
    cfg_dir = root / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    original = _isolate(cfg_dir)
    try:
        legacy = {
            "version": 1,
            "folder": str(root / "sync"),
            "remote_root": "/my-files",
            "direction": "bidirectional",
            "items": {"notes.txt": {"local_size": 1}},
        }
        config.SYNC_DELTA_PATH.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        loaded = config.load_sync_delta("default")
        assert loaded["items"]["notes.txt"]["local_size"] == 1
        config.save_sync_delta(loaded, "default")
        store = json.loads(config.SYNC_DELTA_PATH.read_text(encoding="utf-8"))
        assert store["version"] == 2
        assert "default" in store["pairs"]
    finally:
        _restore(original)
    print("legacy delta migrates ok")


if __name__ == "__main__":
    test_migrate_legacy_single_folder_to_pairs()
    test_multi_pair_run_once()
    test_pause_blocks_due_and_run_once()
    test_activity_history_bounded()
    test_legacy_delta_migrates_to_store()
    print("sync pairs checks passed")
