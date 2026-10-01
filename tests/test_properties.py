#!/usr/bin/env python3
"""Focused checks for read-only Properties field formatting."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import (  # noqa: E402
    format_item_type,
    format_share_status,
    item_property_rows,
)
from proton_drive_desktop.cli import format_size, node_size  # noqa: E402


def test_format_item_type() -> None:
    assert format_item_type("file") == "File"
    assert format_item_type("folder") == "Folder"
    assert format_item_type("photo") == "Photo"
    assert format_item_type("album") == "Album"
    assert format_item_type("day") == "Day"
    assert format_item_type("invitation") == "Invitation"
    assert format_item_type("") == "Unknown"
    assert format_item_type("custom-kind") == "Custom Kind"


def test_format_share_status() -> None:
    assert format_share_status() == "Not shared"
    assert format_share_status(is_shared=True) == "Shared"
    assert format_share_status(is_shared_by_url=True) == "Shared via link"
    assert format_share_status(is_shared=True, is_shared_by_url=True) == "Shared (people and link)"


def test_item_property_rows_file() -> None:
    node = {
        "type": "file",
        "name": "report.pdf",
        "modificationTime": "2024-06-15T12:30:00Z",
        "isShared": True,
        "isSharedByUrl": False,
        "activeRevision": {"claimedSize": 2048},
    }
    rows = dict(
        item_property_rows(
            name="report.pdf",
            kind="file",
            size=node_size(node),
            modified=str(node["modificationTime"]),
            path="/my-files/report.pdf",
            is_shared=bool(node.get("isShared")),
            is_shared_by_url=bool(node.get("isSharedByUrl")),
        )
    )
    assert rows["Name"] == "report.pdf"
    assert rows["Type"] == "File"
    assert rows["Size"] == format_size(2048)
    assert rows["Share status"] == "Shared"
    assert rows["Full path"] == "/my-files/report.pdf"
    assert "2024" in rows["Modified"] or "Jun" in rows["Modified"]


def test_item_property_rows_folder_unshared() -> None:
    rows = dict(
        item_property_rows(
            name="Docs",
            kind="folder",
            size=None,
            modified="",
            path="/my-files/Docs",
            is_shared=False,
            is_shared_by_url=False,
        )
    )
    assert rows["Type"] == "Folder"
    assert rows["Size"] == "—"
    assert rows["Modified"] == "—"
    assert rows["Share status"] == "Not shared"
    assert rows["Full path"] == "/my-files/Docs"


def test_item_property_rows_link_share() -> None:
    rows = dict(
        item_property_rows(
            name="photo.jpg",
            kind="photo",
            size=512,
            modified="2025-01-02T08:00:00Z",
            path="/photos/uid-1",
            is_shared=False,
            is_shared_by_url=True,
        )
    )
    assert rows["Type"] == "Photo"
    assert rows["Size"] == format_size(512)
    assert rows["Share status"] == "Shared via link"


if __name__ == "__main__":
    test_format_item_type()
    test_format_share_status()
    test_item_property_rows_file()
    test_item_property_rows_folder_unshared()
    test_item_property_rows_link_share()
    print("properties checks passed")
