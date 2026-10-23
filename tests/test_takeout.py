#!/usr/bin/env python3
"""Offline checks for takeout include normalization (Settings wizard helper)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.cli import (  # noqa: E402
    TAKEOUT_INCLUDE_CHOICES,
    normalize_takeout_includes,
)


def test_takeout_include_choices() -> None:
    assert TAKEOUT_INCLUDE_CHOICES == ("my-files", "devices", "photos", "revisions")


def test_normalize_takeout_includes() -> None:
    assert normalize_takeout_includes(None) == []
    assert normalize_takeout_includes([]) == []
    assert normalize_takeout_includes(["photos", "my-files", "nope"]) == ["my-files", "photos"]
    assert normalize_takeout_includes(["revisions", "devices", "devices", " Photos "]) == [
        "devices",
        "photos",
        "revisions",
    ]
    assert normalize_takeout_includes(list(TAKEOUT_INCLUDE_CHOICES)) == list(TAKEOUT_INCLUDE_CHOICES)


if __name__ == "__main__":
    test_takeout_include_choices()
    test_normalize_takeout_includes()
    print("takeout checks passed")
