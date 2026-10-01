#!/usr/bin/env python3
"""Focused checks for list/grid view mode and extension-aware icons."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import file_type_icon, normalize_view_mode  # noqa: E402


def test_normalize_view_mode() -> None:
    assert normalize_view_mode("list") == "list"
    assert normalize_view_mode("LIST") == "list"
    assert normalize_view_mode("") == "list"
    assert normalize_view_mode(None) == "list"
    assert normalize_view_mode("grid") == "grid"
    assert normalize_view_mode(" Grid ") == "grid"
    assert normalize_view_mode("tiles") == "list"


def test_file_type_icon_kinds() -> None:
    assert file_type_icon(kind="folder") == "folder"
    assert file_type_icon(kind="invitation") == "mail-unread-symbolic"
    assert file_type_icon(kind="day") == "folder-pictures"
    assert file_type_icon(kind="album") == "folder-pictures"
    assert file_type_icon(kind="photo", media_type="image/jpeg") == "image-x-generic"
    assert file_type_icon(kind="photo", media_type="video/mp4") == "video-x-generic"


def test_file_type_icon_extensions() -> None:
    assert file_type_icon(kind="file", name="Report.PDF") == "application-pdf"
    assert file_type_icon(kind="file", name="sheet.xlsx") == "x-office-spreadsheet"
    assert file_type_icon(kind="file", name="deck.pptx") == "x-office-presentation"
    assert file_type_icon(kind="file", name="notes.txt") == "text-x-generic"
    assert file_type_icon(kind="file", name="archive.zip") == "package-x-generic"
    assert file_type_icon(kind="file", name="clip.mp4") == "video-x-generic"
    assert file_type_icon(kind="file", name="song.mp3") == "audio-x-generic"
    assert file_type_icon(kind="file", name="photo.png") == "image-x-generic"
    assert file_type_icon(kind="file", name="app.py") == "text-x-script"


def test_file_type_icon_mime_overrides_extension() -> None:
    assert (
        file_type_icon(kind="file", name="odd.bin", media_type="application/pdf")
        == "application-pdf"
    )
    assert (
        file_type_icon(kind="file", name="clip.bin", media_type="video/webm")
        == "video-x-generic"
    )


if __name__ == "__main__":
    test_normalize_view_mode()
    test_file_type_icon_kinds()
    test_file_type_icon_extensions()
    test_file_type_icon_mime_overrides_extension()
    print("file view checks passed")
