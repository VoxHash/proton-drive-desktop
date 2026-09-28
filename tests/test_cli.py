#!/usr/bin/env python3
"""Live checks against the official Proton Drive CLI on this machine."""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_linux.cli import (  # noqa: E402
    CliError,
    ProtonDriveCli,
    account_email,
    added_by_email,
    format_size,
    invitation_name,
    invitation_uid,
    join_path,
    member_email,
    member_role,
    node_name,
)


def test_join_path() -> None:
    assert join_path("/my-files", "a/b") == "/my-files/a\\/b"
    assert format_size(1024) == "1.0 KB"


class CaptureCli(ProtonDriveCli):
    def __init__(self) -> None:
        self.binary = "proton-drive"
        self.calls: list[tuple[list[str], bool]] = []

    def run(self, args: list[str], *, json_out: bool = True, timeout: int = 180):  # type: ignore[override]
        self.calls.append((list(args), json_out))
        return None


def test_filesystem_mutate_commands() -> None:
    cli = CaptureCli()
    cli.rename("/my-files/a", "b")
    cli.copy("/my-files/a", "/my-files/dest")
    cli.copy("/my-files/a", "/my-files/dest", name="a-copy")
    cli.move("/my-files/a", "/my-files/dest")
    cli.empty_trash()
    cli.trash("/my-files/a")
    cli.restore("/trash/a")
    cli.delete("/trash/a")
    assert cli.calls == [
        (["filesystem", "rename", "/my-files/a", "b"], False),
        (["filesystem", "copy", "/my-files/a", "/my-files/dest"], False),
        (["filesystem", "copy", "-n", "a-copy", "/my-files/a", "/my-files/dest"], False),
        (["filesystem", "move", "/my-files/a", "/my-files/dest"], False),
        (["filesystem", "empty-trash"], False),
        (["filesystem", "trash", "/my-files/a"], False),
        (["filesystem", "restore", "/trash/a"], False),
        (["filesystem", "delete", "/trash/a"], False),
    ]


def test_invitation_helpers() -> None:
    item = {
        "uid": "inv-uid-1",
        "inviteeEmail": "reviewer@proton.me",
        "role": "editor",
        "addedByEmail": {"ok": True, "value": "glytherra@proton.me"},
        "node": {"name": {"ok": True, "value": "Reports"}, "type": "folder"},
    }
    assert invitation_uid(item) == "inv-uid-1"
    assert invitation_name(item) == "Reports"
    assert added_by_email(item) == "glytherra@proton.me"
    assert member_email(item) == "reviewer@proton.me"
    assert member_role(item) == "editor"
    assert invitation_uid({"invitationUid": "legacy"}) == "legacy"


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


def test_live_sharing_and_invitations() -> None:
    cli = ProtonDriveCli()
    invites = cli.invitation_list()
    assert isinstance(invites, list)
    items = cli.list("/my-files")
    folder = next((n for n in items if n.get("type") == "folder"), None)
    assert folder is not None, "expected a real folder in My files"
    path = join_path("/my-files", node_name(folder))
    status = cli.sharing_status(path)
    assert status is None or isinstance(status, dict)
    if isinstance(status, dict):
        assert isinstance(status.get("protonInvitations") or [], list)
        assert isinstance(status.get("members") or [], list)
    try:
        cli.invitation_accept("NOT-A-REAL-UID")
        raise AssertionError("expected CliError for fake invitation UID")
    except CliError as exc:
        text = str(exc).lower()
        assert "invitation" in text or "invalid" in text
    try:
        cli.sharing_invite(path, ["glytherra@proton.me"], role="viewer")
        raise AssertionError("expected CliError when inviting yourself")
    except CliError as exc:
        text = str(exc).lower()
        assert "yourself" in text or "share" in text
    print("sharing ok", "invites", len(invites), "status", "none" if status is None else "dict", path)


def test_empty_trash_help() -> None:
    cli = ProtonDriveCli()
    proc = subprocess.run(
        [cli.binary, "filesystem", "empty-trash", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    text = f"{proc.stdout}\n{proc.stderr}"
    assert "filesystem empty-trash" in text
    assert "/trash" in text or "Permanently deletes" in text
    trash = cli.list("/trash")
    assert isinstance(trash, list)
    print("empty-trash help ok; live empty-trash skipped, trash already has", len(trash), "user item(s)")


def test_live_rename_copy_move() -> None:
    cli = ProtonDriveCli()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    original = f"pdl-op-{stamp}"
    renamed = f"{original}-renamed"
    copied = f"{original}-copy"
    dest = f"{original}-dest"
    created = [original, renamed, copied, dest]
    try:
        cli.mkdir("/my-files", original)
        cli.mkdir("/my-files", dest)
        cli.rename(join_path("/my-files", original), renamed)
        names = {node_name(n) for n in cli.list("/my-files")}
        assert renamed in names
        assert original not in names
        cli.copy(join_path("/my-files", renamed), "/my-files", name=copied)
        names = {node_name(n) for n in cli.list("/my-files")}
        assert copied in names
        cli.move(join_path("/my-files", copied), join_path("/my-files", dest))
        dest_names = {node_name(n) for n in cli.list(join_path("/my-files", dest))}
        assert copied in dest_names
        root_names = {node_name(n) for n in cli.list("/my-files")}
        assert copied not in root_names
        cli.trash(join_path(join_path("/my-files", dest), copied))
        cli.restore(join_path("/trash", copied))
        restored_dest = {node_name(n) for n in cli.list(join_path("/my-files", dest))}
        assert copied in restored_dest
        print("rename/copy/move/restore ok", renamed, copied, dest)
    finally:
        try:
            live = cli.list("/my-files")
        except CliError:
            live = []
        for node in live:
            name = node_name(node)
            if name in created or name.startswith(f"pdl-op-{stamp}"):
                try:
                    cli.trash(join_path("/my-files", name))
                except CliError:
                    pass
        try:
            trash_nodes = cli.list("/trash")
        except CliError:
            trash_nodes = []
        for node in trash_nodes:
            name = node_name(node)
            if name in created or name.startswith(f"pdl-op-{stamp}"):
                try:
                    cli.delete(join_path("/trash", name))
                except CliError:
                    pass


if __name__ == "__main__":
    test_join_path()
    test_filesystem_mutate_commands()
    test_invitation_helpers()
    test_live_my_files()
    test_live_photos_timeline()
    test_live_sharing_and_invitations()
    test_empty_trash_help()
    test_live_rename_copy_move()
    print("all checks passed")
