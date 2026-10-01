#!/usr/bin/env python3
"""Legacy ~/.config/proton-drive-linux → proton-drive-desktop merge checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import config  # noqa: E402


def _reset_migrate_flag() -> None:
    config._did_migrate_legacy = False


def test_merge_prefers_new_keeps_missing_from_old() -> None:
    legacy = {
        "theme": "light",
        "language": "en",
        "download_folder": "/old/downloads",
        "sync_folder": "/old/sync",
        "sync_enabled": True,
        "cli_path": "/old/cli",
        "autostart": True,
    }
    current = {
        "theme": "dark",
        "language": "ja",
    }
    merged = config._merge_gui_settings(legacy, current)
    assert merged["theme"] == "dark"
    assert merged["language"] == "ja"
    assert merged["download_folder"] == "/old/downloads"
    assert merged["sync_folder"] == "/old/sync"
    assert merged["sync_enabled"] is True
    assert merged["cli_path"] == "/old/cli"
    assert merged["autostart"] is True


def test_migrate_copies_gui_then_removes_legacy(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path("/tmp/proton-drive-desktop-migrate-test")
    if base.exists():
        for child in base.iterdir():
            if child.is_dir():
                for nested in child.iterdir():
                    nested.unlink(missing_ok=True)
                child.rmdir()
            else:
                child.unlink(missing_ok=True)
    else:
        base.mkdir(parents=True)

    legacy_dir = base / "legacy"
    new_dir = base / "new"
    legacy_dir.mkdir()
    legacy_gui = legacy_dir / "gui.json"
    legacy_gui.write_text(
        json.dumps(
            {
                "theme": "light",
                "language": "en",
                "download_folder": str(base),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(base),
                "sync_enabled": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (legacy_dir / "sync-status.json").write_text(
        json.dumps({"state": "idle", "message": "ok"}) + "\n",
        encoding="utf-8",
    )

    originals = (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.LEGACY_CONFIG_DIR,
        config._DEFAULT_CONFIG_DIR,
    )
    _reset_migrate_flag()
    config._DEFAULT_CONFIG_DIR = new_dir
    config.CONFIG_DIR = new_dir
    config.CONFIG_PATH = new_dir / "gui.json"
    config.SYNC_STATUS_PATH = new_dir / "sync-status.json"
    config.LEGACY_CONFIG_DIR = legacy_dir
    try:
        loaded = config.load()
        assert loaded["theme"] == "light"
        assert loaded["sync_enabled"] is True
        assert config.CONFIG_PATH.is_file()
        assert config.SYNC_STATUS_PATH.is_file()
        assert not legacy_dir.exists()
    finally:
        (
            config.CONFIG_DIR,
            config.CONFIG_PATH,
            config.SYNC_STATUS_PATH,
            config.LEGACY_CONFIG_DIR,
            config._DEFAULT_CONFIG_DIR,
        ) = originals
        _reset_migrate_flag()


def test_migrate_does_not_wipe_newer_gui(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path("/tmp/proton-drive-desktop-migrate-merge-test")
    base.mkdir(parents=True, exist_ok=True)
    legacy_dir = base / "legacy2"
    new_dir = base / "new2"
    legacy_dir.mkdir(exist_ok=True)
    new_dir.mkdir(exist_ok=True)
    (legacy_dir / "gui.json").write_text(
        json.dumps(
            {
                "theme": "light",
                "language": "en",
                "download_folder": str(base),
                "cli_path": "/legacy/cli",
                "autostart": True,
                "sync_folder": str(base),
                "sync_enabled": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (new_dir / "gui.json").write_text(
        json.dumps(
            {
                "theme": "dark",
                "language": "ja",
                "download_folder": str(base),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(base),
                "sync_enabled": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    originals = (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.LEGACY_CONFIG_DIR,
        config._DEFAULT_CONFIG_DIR,
    )
    _reset_migrate_flag()
    config._DEFAULT_CONFIG_DIR = new_dir
    config.CONFIG_DIR = new_dir
    config.CONFIG_PATH = new_dir / "gui.json"
    config.SYNC_STATUS_PATH = new_dir / "sync-status.json"
    config.LEGACY_CONFIG_DIR = legacy_dir
    try:
        loaded = config.load()
        assert loaded["theme"] == "dark"
        assert loaded["language"] == "ja"
        assert loaded["sync_enabled"] is False
        assert loaded["autostart"] is False
        assert not (legacy_dir / "gui.json").exists()
    finally:
        (
            config.CONFIG_DIR,
            config.CONFIG_PATH,
            config.SYNC_STATUS_PATH,
            config.LEGACY_CONFIG_DIR,
            config._DEFAULT_CONFIG_DIR,
        ) = originals
        _reset_migrate_flag()


if __name__ == "__main__":
    test_merge_prefers_new_keeps_missing_from_old()
    test_migrate_copies_gui_then_removes_legacy()
    test_migrate_does_not_wipe_newer_gui()
    print("config migrate checks passed")
