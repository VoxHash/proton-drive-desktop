#!/usr/bin/env python3
"""Open vs Download decision helpers — Open must not equal Download for files."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.app import (  # noqa: E402
    OPEN_INTENT_INVITATION,
    OPEN_INTENT_LAUNCH,
    OPEN_INTENT_NAVIGATE,
    OPEN_INTENT_REFUSE,
    open_intent_for_kind,
    resolve_downloaded_path,
    snapshot_dir_names,
)


def test_open_intent_matrix() -> None:
    assert open_intent_for_kind("folder") == OPEN_INTENT_NAVIGATE
    assert open_intent_for_kind("day") == OPEN_INTENT_NAVIGATE
    assert open_intent_for_kind("album") == OPEN_INTENT_NAVIGATE
    assert open_intent_for_kind("file") == OPEN_INTENT_LAUNCH
    assert open_intent_for_kind("photo") == OPEN_INTENT_LAUNCH
    assert open_intent_for_kind("invitation") == OPEN_INTENT_INVITATION
    # Containers navigate; files launch — never the same branch for folder vs file.
    assert open_intent_for_kind("folder") != open_intent_for_kind("file")


def test_resolve_downloaded_path_exact_and_newcomer(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="proton-drive-desktop-open-test-"))
    before = snapshot_dir_names(base)
    report = base / "Report.pdf"
    report.write_text("x", encoding="utf-8")
    assert resolve_downloaded_path(base, "Report.pdf", before_names=before) == report

    before2 = snapshot_dir_names(base)
    renamed = base / "Report (1).pdf"
    renamed.write_text("y", encoding="utf-8")
    found = resolve_downloaded_path(base, "Report.pdf", before_names=before2)
    assert found == renamed


def test_resolve_missing() -> None:
    missing = Path("/tmp/proton-drive-desktop-open-missing-dir-xyz")
    assert resolve_downloaded_path(missing, "a.txt") is None


if __name__ == "__main__":
    test_open_intent_matrix()
    test_resolve_downloaded_path_exact_and_newcomer()
    test_resolve_missing()
    # OPEN_INTENT_REFUSE reserved for unknown non-downloadable chrome
    assert OPEN_INTENT_REFUSE == "refuse"
    print("open/download checks passed")
