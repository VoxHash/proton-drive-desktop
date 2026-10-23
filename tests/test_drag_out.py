#!/usr/bin/env python3
"""Focused checks for drag-out download eligibility and staging helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import (  # noqa: E402
    collect_staged_paths,
    drag_out_section_allowed,
    drag_out_selection_key,
    filter_drag_out_items,
)
from proton_drive_desktop import config  # noqa: E402


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


def test_drag_out_selection_key_stable() -> None:
    a = SimpleNamespace(path="/my-files/b.txt")
    b = SimpleNamespace(path="/my-files/a.txt")
    assert drag_out_selection_key([a, b]) == ("/my-files/a.txt", "/my-files/b.txt")
    assert drag_out_selection_key([b, a]) == drag_out_selection_key([a, b])


def test_collect_staged_paths(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="proton-drive-desktop-drag-test-"))
    (base / "report.pdf").write_text("x", encoding="utf-8")
    (base / "Docs").mkdir()
    (base / ".proton-drive-desktop-drag-key").write_text("/my-files/a\n", encoding="utf-8")
    paths = collect_staged_paths(base)
    names = {p.name for p in paths}
    assert "report.pdf" in names
    assert "Docs" in names
    assert ".proton-drive-desktop-drag-key" in names
    assert collect_staged_paths(base / "missing") == []


def test_drag_out_enabled_default_off() -> None:
    assert config._DEFAULTS.get("drag_out_enabled") is False
    folder = Path(tempfile.mkdtemp(prefix="proton-drive-desktop-drag-cfg-"))
    original_dir, original_path = config.CONFIG_DIR, config.CONFIG_PATH
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    try:
        config.save({})
        loaded = config.load()
        assert loaded.get("drag_out_enabled") is False
        config.save({"drag_out_enabled": True})
        assert config.load().get("drag_out_enabled") is True
    finally:
        config.CONFIG_DIR = original_dir
        config.CONFIG_PATH = original_path


if __name__ == "__main__":
    test_drag_out_section_allowed()
    test_filter_drag_out_items()
    test_drag_out_prepare_requires_my_files_selection()
    test_drag_out_selection_key_stable()
    test_collect_staged_paths()
    test_drag_out_enabled_default_off()
    print("drag-out checks passed")
