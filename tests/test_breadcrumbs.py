#!/usr/bin/env python3
"""Focused checks for clickable breadcrumb trail truncation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import crumbs_after_navigate  # noqa: E402


def test_navigate_to_ancestor() -> None:
    crumbs = [
        ("My files", "/my-files"),
        ("Documents", "/my-files/Documents"),
        ("Work", "/my-files/Documents/Work"),
    ]
    trimmed = crumbs_after_navigate(crumbs, 1)
    assert trimmed == [
        ("My files", "/my-files"),
        ("Documents", "/my-files/Documents"),
    ]


def test_navigate_to_root() -> None:
    crumbs = [
        ("My files", "/my-files"),
        ("Documents", "/my-files/Documents"),
    ]
    trimmed = crumbs_after_navigate(crumbs, 0)
    assert trimmed == [("My files", "/my-files")]


def test_current_crumb_is_noop() -> None:
    crumbs = [
        ("My files", "/my-files"),
        ("Documents", "/my-files/Documents"),
    ]
    assert crumbs_after_navigate(crumbs, 1) is None
    assert crumbs_after_navigate(crumbs, -1) is None
    assert crumbs_after_navigate(crumbs, 5) is None
    assert crumbs_after_navigate([], 0) is None


if __name__ == "__main__":
    test_navigate_to_ancestor()
    test_navigate_to_root()
    test_current_crumb_is_noop()
    print("breadcrumb checks passed")
