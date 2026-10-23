#!/usr/bin/env python3
"""Focused checks for drag-out download eligibility helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import (  # noqa: E402
    drag_out_section_allowed,
    filter_drag_out_items,
)


def test_drag_out_section_allowed() -> None:
    assert drag_out_section_allowed("/my-files") is True
    assert drag_out_section_allowed("/photos") is False
    assert drag_out_section_allowed("/shared-with-me") is False
    assert drag_out_section_allowed("/trash") is False


def test_filter_drag_out_items() -> None:
    file_item = SimpleNamespace(kind="file", path="/my-files/a.txt")
    folder_item = SimpleNamespace(kind="folder", path="/my-files/docs")
    shared = SimpleNamespace(kind="share", path="/shared-with-me/x")
    invitation = SimpleNamespace(kind="invitation", path="/shared-with-me/invite")
    assert filter_drag_out_items("/my-files", [file_item, folder_item]) == [file_item, folder_item]
    assert filter_drag_out_items("/my-files", [file_item, shared, invitation]) == [file_item]
    assert filter_drag_out_items("/photos", [file_item]) == []
    assert filter_drag_out_items("/trash", [folder_item]) == []


def test_drag_out_prepare_requires_my_files_selection() -> None:
    """Regression: empty / wrong-section selection must not start a FileList drag."""
    assert filter_drag_out_items("/my-files", []) == []
    photo = SimpleNamespace(kind="file", path="/photos/1.jpg")
    assert filter_drag_out_items("/my-files", [photo]) == []


if __name__ == "__main__":
    test_drag_out_section_allowed()
    test_filter_drag_out_items()
    test_drag_out_prepare_requires_my_files_selection()
    print("drag-out checks passed")
