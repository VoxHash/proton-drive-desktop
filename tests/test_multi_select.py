#!/usr/bin/env python3
"""Focused checks for multi-select bulk trash / download / move helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import (  # noqa: E402
    dest_is_inside_source,
    is_downloadable_kind,
    is_movable_item,
)


def test_is_downloadable_kind() -> None:
    assert is_downloadable_kind("file")
    assert is_downloadable_kind("folder")
    assert is_downloadable_kind("photo")
    assert not is_downloadable_kind("day")
    assert not is_downloadable_kind("album")
    assert not is_downloadable_kind("invitation")


def test_is_movable_item() -> None:
    assert is_movable_item("file", "/my-files/a.txt", "/my-files")
    assert is_movable_item("folder", "/my-files/Docs", "/my-files")
    assert is_movable_item("file", "/shared-with-me/x", "/shared-with-me")
    assert not is_movable_item("invitation", "/shared-with-me/inv", "/shared-with-me")
    assert not is_movable_item("day", "/photos/2024-01-01", "/photos")
    assert not is_movable_item("album", "/albums/Trip", "/photos")
    assert not is_movable_item("file", "/trash/a.txt", "/trash")
    assert not is_movable_item("file", "/trash/a.txt", "/my-files")
    assert not is_movable_item("folder", "/my-files", "/my-files")
    assert not is_movable_item("folder", "/photos", "/photos")


def test_dest_is_inside_source() -> None:
    assert dest_is_inside_source("/my-files/Docs", "/my-files/Docs")
    assert dest_is_inside_source("/my-files/Docs/sub", "/my-files/Docs")
    assert not dest_is_inside_source("/my-files", "/my-files/Docs")
    assert not dest_is_inside_source("/my-files/Other", "/my-files/Docs")
    assert not dest_is_inside_source("/my-files/DocsBackup", "/my-files/Docs")


def test_bulk_downloadable_filter() -> None:
    kinds = ["file", "folder", "day", "album", "photo", "invitation"]
    kept = [kind for kind in kinds if is_downloadable_kind(kind)]
    assert kept == ["file", "folder", "photo"]


def test_bulk_movable_filter() -> None:
    rows = [
        ("file", "/my-files/a.txt"),
        ("folder", "/my-files/Docs"),
        ("file", "/trash/gone"),
        ("invitation", "/shared-with-me/i"),
        ("day", "/photos/2024-01-01"),
    ]
    kept = [path for kind, path in rows if is_movable_item(kind, path, "/my-files")]
    assert kept == ["/my-files/a.txt", "/my-files/Docs"]


if __name__ == "__main__":
    test_is_downloadable_kind()
    test_is_movable_item()
    test_dest_is_inside_source()
    test_bulk_downloadable_filter()
    test_bulk_movable_filter()
    print("multi-select checks passed")
