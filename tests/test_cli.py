#!/usr/bin/env python3
"""Live checks against the official Proton Drive CLI on this machine."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_linux.cli import (  # noqa: E402
    ProtonDriveCli,
    account_email,
    format_size,
    join_path,
    node_name,
)


def test_join_path() -> None:
    assert join_path("/my-files", "a/b") == "/my-files/a\\/b"
    assert format_size(1024) == "1.0 KB"


def test_live_my_files() -> None:
    cli = ProtonDriveCli()
    items = cli.list("/my-files")
    assert isinstance(items, list)
    assert items, "expected real Drive contents"
    names = [node_name(i) for i in items]
    assert all(names)
    email = account_email(items)
    assert email and "@" in email
    shared = cli.list("/shared-with-me")
    assert isinstance(shared, list)
    trash = cli.list("/trash")
    assert isinstance(trash, list)
    print("live ok", email, "files", len(items), "shared", len(shared), "trash", len(trash))


def test_live_photos_timeline() -> None:
    cli = ProtonDriveCli()
    items = cli.photo_timeline()
    assert isinstance(items, list)
    assert items, "expected real Photos timeline"
    first = items[0]
    assert first.get("nodeUid")
    assert first.get("captureTime")
    albums = cli.album_list()
    assert isinstance(albums, list)
    info = cli.info(f"/photos/{first['nodeUid']}")
    assert node_name(info)
    print("photos ok", len(items), "albums", len(albums), node_name(info))


if __name__ == "__main__":
    test_join_path()
    test_live_my_files()
    test_live_photos_timeline()
    print("all checks passed")
