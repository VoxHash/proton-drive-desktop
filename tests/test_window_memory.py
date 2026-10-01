#!/usr/bin/env python3
"""Window size and last-path memory helpers + gui.json persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import config  # noqa: E402
from proton_drive_desktop.app import (  # noqa: E402
    crumbs_for_path,
    normalize_last_path,
    normalize_window_height,
    normalize_window_width,
    section_for_path,
)


def test_normalize_last_path() -> None:
    assert normalize_last_path("/my-files/Docs") == "/my-files/Docs"
    assert normalize_last_path("/my-files/Docs/") == "/my-files/Docs"
    assert normalize_last_path("/photos/2024-01-15") == "/photos/2024-01-15"
    assert normalize_last_path("/albums/Vacation") == "/albums/Vacation"
    assert normalize_last_path("/albums") == "/photos"
    assert normalize_last_path("") == "/my-files"
    assert normalize_last_path(None) == "/my-files"
    assert normalize_last_path("relative") == "/my-files"
    assert normalize_last_path("/unknown") == "/my-files"
    assert normalize_last_path("/invitations/x") == "/my-files"


def test_section_for_path() -> None:
    assert section_for_path("/my-files/a/b") == "/my-files"
    assert section_for_path("/photos/2024-01-15") == "/photos"
    assert section_for_path("/albums/Trip") == "/photos"
    assert section_for_path("/shared-with-me/x") == "/shared-with-me"
    assert section_for_path("/trash/y") == "/trash"
    assert section_for_path("/nope") == "/my-files"


def test_crumbs_for_path() -> None:
    crumbs = crumbs_for_path("/my-files/Documents/Work")
    assert [p for _l, p in crumbs] == [
        "/my-files",
        "/my-files/Documents",
        "/my-files/Documents/Work",
    ]
    assert crumbs[0][0]  # translated section label
    assert crumbs[1][0] == "Documents"
    assert crumbs[2][0] == "Work"

    album = crumbs_for_path("/albums/Vacation")
    assert [p for _l, p in album] == ["/photos", "/albums/Vacation"]
    assert album[1][0] == "Vacation"

    day = crumbs_for_path("/photos/2024-01-15")
    assert [p for _l, p in day] == ["/photos", "/photos/2024-01-15"]
    assert day[1][0] == "Jan 15, 2024"

    root = crumbs_for_path("/trash")
    assert root == [(root[0][0], "/trash")]


def test_crumbs_escaped_segment() -> None:
    crumbs = crumbs_for_path("/my-files/a\\/b/c")
    assert [p for _l, p in crumbs] == ["/my-files", "/my-files/a\\/b", "/my-files/a\\/b/c"]
    assert crumbs[1][0] == "a/b"
    assert crumbs[2][0] == "c"


def test_normalize_window_geometry() -> None:
    assert normalize_window_width(1400) == 1400
    assert normalize_window_height(900) == 900
    assert normalize_window_width(0) == 1180
    assert normalize_window_height(-1) == 760
    assert normalize_window_width("bad") == 1180
    assert normalize_window_height(None) == 760
    assert normalize_window_width(50) == 400
    assert normalize_window_height(50) == 300


def test_config_persists_window_memory(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path("/tmp/proton-drive-desktop-window-memory-test")
    base.mkdir(parents=True, exist_ok=True)
    folder = base / "cfg"
    if folder.exists():
        for child in folder.iterdir():
            if child.is_file():
                child.unlink()
    folder.mkdir(exist_ok=True)

    originals = (
        config.CONFIG_DIR,
        config.CONFIG_PATH,
        config.SYNC_STATUS_PATH,
        config.LEGACY_CONFIG_DIR,
        config._DEFAULT_CONFIG_DIR,
        config._did_migrate_legacy,
    )
    config._did_migrate_legacy = True
    config._DEFAULT_CONFIG_DIR = folder
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    config.SYNC_STATUS_PATH = folder / "sync-status.json"
    config.LEGACY_CONFIG_DIR = folder / "legacy-missing"
    try:
        loaded = config.load()
        assert loaded["window_width"] == 1180
        assert loaded["window_height"] == 760
        assert loaded["window_maximized"] is False
        assert loaded["last_path"] == "/my-files"

        config.save(
            {
                **loaded,
                "window_width": 1440,
                "window_height": 900,
                "window_maximized": True,
                "last_path": "/my-files/Projects",
            }
        )
        raw = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
        assert raw["window_width"] == 1440
        assert raw["window_height"] == 900
        assert raw["window_maximized"] is True
        assert raw["last_path"] == "/my-files/Projects"

        again = config.load()
        assert again["window_width"] == 1440
        assert again["window_height"] == 900
        assert again["window_maximized"] is True
        assert again["last_path"] == "/my-files/Projects"

        config.save({**again, "last_path": "/bogus", "window_width": -5})
        fixed = config.load()
        assert fixed["last_path"] == "/my-files"
        assert fixed["window_width"] == 1180
    finally:
        (
            config.CONFIG_DIR,
            config.CONFIG_PATH,
            config.SYNC_STATUS_PATH,
            config.LEGACY_CONFIG_DIR,
            config._DEFAULT_CONFIG_DIR,
            config._did_migrate_legacy,
        ) = originals


if __name__ == "__main__":
    test_normalize_last_path()
    test_section_for_path()
    test_crumbs_for_path()
    test_crumbs_escaped_segment()
    test_normalize_window_geometry()
    test_config_persists_window_memory()
    print("window memory checks passed")
