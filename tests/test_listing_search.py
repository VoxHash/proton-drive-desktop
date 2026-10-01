#!/usr/bin/env python3
"""Focused checks for in-list folder filter matching (Ctrl+F)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import listing_name_matches  # noqa: E402


def test_empty_query_matches_all() -> None:
    assert listing_name_matches("Report.pdf", "")
    assert listing_name_matches("Report.pdf", "   ")


def test_case_insensitive_substring() -> None:
    assert listing_name_matches("Quarterly Report.pdf", "report")
    assert listing_name_matches("Quarterly Report.pdf", "QUARTER")
    assert listing_name_matches("Photos", "pho")
    assert not listing_name_matches("Photos", "video")
    assert not listing_name_matches("alpha", "beta")


def test_filters_sample_listing() -> None:
    names = ["Documents", "Photos", "notes.txt", "README.md", "archive.zip"]
    query = "o"
    matched = [name for name in names if listing_name_matches(name, query)]
    assert matched == ["Documents", "Photos", "notes.txt"]


if __name__ == "__main__":
    test_empty_query_matches_all()
    test_case_insensitive_substring()
    test_filters_sample_listing()
    print("listing search checks passed")
