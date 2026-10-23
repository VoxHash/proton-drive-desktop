#!/usr/bin/env python3
"""Offline checks for deep-search scope helpers and name-walk matching."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.deep_search import (  # noqa: E402
    DEEP_SEARCH_SCOPE_CURRENT,
    DEEP_SEARCH_SCOPE_FILTER,
    DEEP_SEARCH_SCOPE_MY_FILES,
    DEEP_SEARCH_SCOPE_SHARED,
    DeepSearchCancelled,
    deep_search_root,
    deep_search_scope_allowed,
    listing_name_matches,
    normalize_deep_search_scope,
    should_descend_folder,
    walk_name_matches,
)


def test_normalize_and_roots() -> None:
    assert normalize_deep_search_scope("nope") == DEEP_SEARCH_SCOPE_FILTER
    assert deep_search_root(DEEP_SEARCH_SCOPE_FILTER, current_path="/my-files/a", section="/my-files") is None
    assert deep_search_root(DEEP_SEARCH_SCOPE_MY_FILES, current_path="/my-files/a", section="/my-files") == "/my-files"
    assert deep_search_root(DEEP_SEARCH_SCOPE_SHARED, current_path="/x", section="/photos") == "/shared-with-me"
    assert (
        deep_search_root(DEEP_SEARCH_SCOPE_CURRENT, current_path="/my-files/Docs", section="/my-files")
        == "/my-files/Docs"
    )
    assert deep_search_root(DEEP_SEARCH_SCOPE_CURRENT, current_path="/photos/day", section="/photos") is None
    assert deep_search_scope_allowed(DEEP_SEARCH_SCOPE_CURRENT, section="/my-files") is True
    assert deep_search_scope_allowed(DEEP_SEARCH_SCOPE_CURRENT, section="/trash") is False


def test_should_descend_and_match() -> None:
    assert should_descend_folder("folder")
    assert not should_descend_folder("file")
    assert listing_name_matches("Invoice.pdf", "invoice")
    assert not listing_name_matches("Invoice.pdf", "tax")


class _FakeCli:
    def __init__(self, tree: dict[str, list[dict]]) -> None:
        self.tree = tree
        self.calls: list[str] = []

    def list(self, path: str):
        self.calls.append(path)
        return list(self.tree.get(path, []))


def test_walk_name_matches_bfs() -> None:
    cli = _FakeCli(
        {
            "/my-files": [
                {"type": "folder", "name": "Docs"},
                {"type": "file", "name": "readme.txt"},
            ],
            "/my-files/Docs": [
                {"type": "file", "name": "Report.pdf"},
                {"type": "folder", "name": "Archive"},
            ],
            "/my-files/Docs/Archive": [
                {"type": "file", "name": "old-report.pdf"},
            ],
        }
    )
    hits = walk_name_matches(cli, "/my-files", "report")  # type: ignore[arg-type]
    names = {h.name for h in hits}
    assert names == {"Report.pdf", "old-report.pdf"}
    assert "/my-files" in cli.calls
    assert "/my-files/Docs" in cli.calls
    assert "/my-files/Docs/Archive" in cli.calls


def test_walk_cancel() -> None:
    cli = _FakeCli({"/my-files": [{"type": "folder", "name": "A"}]})
    cancel = threading.Event()
    cancel.set()
    try:
        walk_name_matches(cli, "/my-files", "x", cancel=cancel)  # type: ignore[arg-type]
        raise AssertionError("expected DeepSearchCancelled")
    except DeepSearchCancelled:
        pass


def test_empty_query_returns_no_hits() -> None:
    cli = _FakeCli({"/my-files": [{"type": "file", "name": "a.txt"}]})
    assert walk_name_matches(cli, "/my-files", "  ") == []  # type: ignore[arg-type]


if __name__ == "__main__":
    test_normalize_and_roots()
    test_should_descend_and_match()
    test_walk_name_matches_bfs()
    test_walk_cancel()
    test_empty_query_returns_no_hits()
    print("deep search checks passed")
