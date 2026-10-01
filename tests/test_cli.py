#!/usr/bin/env python3
"""Live checks against the official Proton Drive CLI on this machine."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop.cli import (  # noqa: E402
    CliError,
    ProtonDriveCli,
    account_email,
    added_by_email,
    album_cli_path,
    cli_help_exposes_storage_quota,
    format_size,
    invitation_name,
    invitation_uid,
    join_path,
    member_email,
    member_role,
    node_name,
    parse_version_output,
    photo_cli_path,
)
from proton_drive_desktop.paths import CLI_DOWNLOAD_URL  # noqa: E402


def test_join_path() -> None:
    assert join_path("/my-files", "a/b") == "/my-files/a\\/b"
    assert format_size(1024) == "1.0 KB"
    assert album_cli_path({"name": {"ok": True, "value": "Trip"}}) == "/albums/Trip"
    assert album_cli_path({"path": "/albums/Trip", "uid": "x"}) == "/albums/Trip"
    assert photo_cli_path({"nodeUid": "abc"}) == "/photos/abc"
    assert photo_cli_path({"uid": "xyz"}) == "/photos/xyz"


def test_parse_version_latest() -> None:
    raw = (
        "Proton Drive CLI cli-drive@0.8.0+06e8c605\n"
        "Proton Drive SDK js@0.21.0+06e8c605\n"
        "You are running the latest version."
    )
    info = parse_version_output(raw)
    assert info.cli_version == "0.8.0"
    assert info.app_version == "cli-drive@0.8.0+06e8c605"
    assert info.sdk_version == "js@0.21.0+06e8c605"
    assert info.latest is True
    assert info.update_available is False
    assert info.newest_version == "0.8.0"
    assert info.status_line == "You are running the latest version."
    assert info.download_url == CLI_DOWNLOAD_URL
    assert "latest" in info.summary()


def test_parse_version_newer() -> None:
    raw = (
        "Proton Drive CLI cli-drive@0.7.0+06e8c605\n"
        "Proton Drive SDK js@0.20.0+06e8c605\n"
        "A newer version is available: 0.8.0 (you have 0.7.0).\n"
        "Download at https://proton.me/download/drive/cli/index.html"
    )
    info = parse_version_output(raw)
    assert info.cli_version == "0.7.0"
    assert info.latest is False
    assert info.update_available is True
    assert info.newest_version == "0.8.0"
    assert info.status_line == "A newer version is available: 0.8.0 (you have 0.7.0)."
    assert info.download_url == "https://proton.me/download/drive/cli/index.html"
    assert "0.8.0 available" in info.summary()


def test_cli_help_exposes_storage_quota() -> None:
    sample_0_8 = """
Usage:
    auth login
    auth logout
    filesystem list [-t TYPE] path
    sharing status path
    invitation list
    album list
    photo timeline [-d]

General options:
    -h|--help: Show extended help for a command
"""
    assert cli_help_exposes_storage_quota(sample_0_8) is False
    # "Usage:" heading must not count as a usage/quota command
    assert cli_help_exposes_storage_quota("Usage:\n    auth login\n") is False
    assert cli_help_exposes_storage_quota("Usage:\n    quota show\n") is True
    assert cli_help_exposes_storage_quota("Usage:\n    account storage\n") is True
    assert cli_help_exposes_storage_quota("Usage:\n    auth usage\n") is True


def test_parse_version_incomplete() -> None:
    raw = "Proton Drive CLI cli-drive@0.8.0+06e8c605\nProton Drive SDK js@0.21.0+06e8c605"
    info = parse_version_output(raw)
    assert info.cli_version == "0.8.0"
    assert info.latest is False
    assert info.update_available is False
    assert "did not report" in info.status_line


def test_parse_transfer_progress_lines() -> None:
    from proton_drive_desktop.cli import parse_transfer_line, scrape_transfer_text

    queue = parse_transfer_line("ℹ Uploaded 0 | Queued 1")
    assert queue is not None
    assert queue.direction == "upload"
    assert queue.completed == 0
    assert queue.queued == 1
    assert "Queued 1" in queue.status_text()

    progress = parse_transfer_line("⠋ 36.07% pdl-progress-pipe.bin (6.00 MiB)")
    assert progress is not None
    assert progress.percent == 36.07
    assert progress.name == "pdl-progress-pipe.bin"
    assert progress.size_label == "6.00 MiB"
    assert "36.07%" in progress.status_text()

    down_queue = parse_transfer_line("ℹ Downloaded 1 | Queued 2")
    assert down_queue is not None
    assert down_queue.direction == "download"
    assert down_queue.completed == 1
    assert down_queue.queued == 2

    summary = parse_transfer_line("  Uploaded: 1 items (4.00 MiB)")
    assert summary is not None
    assert summary.direction == "upload"
    assert summary.summary == "Uploaded: 1 items (4.00 MiB)"

    done = parse_transfer_line("✅ pdl-progress-nov.bin")
    assert done is not None
    assert done.percent == 100.0
    assert done.name == "pdl-progress-nov.bin"

    assert parse_transfer_line("Transfer summary:") is None
    assert parse_transfer_line("2026-09-29T22:40:42.843Z INFO [cli] Version") is None

    leftover, events = scrape_transfer_text(
        "\rℹ Uploaded 0 | Queued 1\r⠋ 10.00% sample.bin (1.00 MiB)\r⠙ 20.50% sample.bin (1.00 MiB)\n"
    )
    assert leftover == ""
    assert len(events) == 3
    assert events[0].queued == 1
    assert events[1].percent == 10.0
    assert events[2].percent == 20.5

    partial, more = scrape_transfer_text("⠋ 1.00% partial.bin (")
    assert partial == "⠋ 1.00% partial.bin ("
    assert more == []


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


def test_album_mutate_commands() -> None:
    cli = CaptureCli()
    cli.album_create("Summer")
    cli.album_update("/albums/Summer", name="Trip")
    cli.album_update("/albums/Trip", cover_photo_uid="uid-1")
    cli.album_add_photo("/albums/Trip", ["/photos/abc"])
    cli.album_remove_photo("/albums/Trip", ["/photos/abc"])
    cli.album_delete("/albums/Trip")
    cli.album_delete("/albums/Trip", save=True, force=True)
    cli.album_photos("/albums/Trip", load_details=False)
    assert cli.calls == [
        (["album", "create", "Summer"], True),
        (["album", "update", "-n", "Trip", "/albums/Summer"], True),
        (["album", "update", "-c", "uid-1", "/albums/Trip"], True),
        (["album", "add-photo", "/albums/Trip", "/photos/abc"], True),
        (["album", "remove-photo", "/albums/Trip", "/photos/abc"], True),
        (["album", "delete", "/albums/Trip"], True),
        (["album", "delete", "-f", "-s", "/albums/Trip"], True),
        (["album", "photos", "/albums/Trip"], True),
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


def test_live_cli_has_no_storage_quota_command() -> None:
    cli = ProtonDriveCli()
    help_text = cli.help_text()
    assert "filesystem list" in help_text.lower() or "filesystem download" in help_text.lower()
    assert cli_help_exposes_storage_quota(help_text) is False
    assert cli.storage_quota_available() is False
    print("cli has no account/storage quota command")


def test_live_version_check() -> None:
    cli = ProtonDriveCli()
    proc = subprocess.run(
        [cli.binary, "version", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    help_text = f"{proc.stdout}\n{proc.stderr}"
    assert "Proton Drive CLI" in help_text
    json_proc = subprocess.run(
        [cli.binary, "version", "-j"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    json_text = (json_proc.stdout or json_proc.stderr or "").strip()
    assert "Proton Drive CLI" in json_text
    try:
        json.loads(json_text)
        raise AssertionError("proton-drive version -j unexpectedly returned JSON")
    except json.JSONDecodeError:
        pass
    raw = cli.version()
    parsed = parse_version_output(raw)
    info = cli.version_info()
    assert parsed.cli_version
    assert parsed.cli_version.count(".") == 2
    assert info.cli_version == parsed.cli_version
    assert info.latest or info.update_available or "did not report" in info.status_line
    if info.latest:
        assert info.update_available is False
        assert "latest version" in info.status_line
    if info.update_available:
        assert info.newest_version
        assert "newer version is available" in info.status_line.lower()
        assert info.download_url.startswith("https://proton.me/")
    json_parsed = parse_version_output(json_text)
    assert json_parsed.cli_version == info.cli_version
    print("version ok", info.cli_version, info.status_line, "json-flag-text", json_parsed.latest or json_parsed.update_available)


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


def test_live_album_management() -> None:
    cli = ProtonDriveCli()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    name = f"pdl-album-{stamp}"
    renamed = f"{name}-renamed"
    created_names = {name, renamed, "pdl-album-20260928084712"}
    path = join_path("/albums", name)
    renamed_path = join_path("/albums", renamed)
    try:
        created = cli.album_create(name)
        assert created is None or isinstance(created, dict)
        if isinstance(created, dict):
            assert node_name(created) == name
            assert created.get("uid")
        albums = cli.album_list()
        names = {node_name(a) for a in albums}
        assert name in names, names
        timeline = cli.photo_timeline()
        assert timeline, "expected real Photos timeline"
        uid = str(timeline[0]["nodeUid"])
        photo_path = photo_cli_path({"nodeUid": uid})
        added = cli.album_add_photo(path, [photo_path])
        if isinstance(added, list) and added and isinstance(added[0], dict):
            assert added[0].get("ok") is True or added[0].get("uid")
        photos = cli.album_photos(path)
        photo_uids = {str(p.get("uid") or p.get("nodeUid") or "") for p in photos}
        assert uid in photo_uids, photo_uids
        cli.album_update(path, name=renamed)
        albums = cli.album_list()
        names = {node_name(a) for a in albums}
        assert renamed in names
        assert name not in names
        cli.album_remove_photo(renamed_path, [photo_path])
        photos = cli.album_photos(renamed_path)
        photo_uids = {str(p.get("uid") or p.get("nodeUid") or "") for p in photos}
        assert uid not in photo_uids
        cli.album_delete(renamed_path, save=True)
        albums = cli.album_list()
        names = {node_name(a) for a in albums}
        assert renamed not in names
        print("album management ok", renamed, "photo", uid[:24])
    finally:
        try:
            live = cli.album_list()
        except CliError:
            live = []
        for album in live:
            album_name = node_name(album)
            if album_name in created_names or album_name.startswith(f"pdl-album-{stamp}"):
                try:
                    cli.album_delete(join_path("/albums", album_name), save=True)
                except CliError:
                    pass


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


def test_delete_help_and_command() -> None:
    cli = CaptureCli()
    cli.delete("/trash/pdl-del-sample")
    assert cli.calls == [(["filesystem", "delete", "/trash/pdl-del-sample"], False)]
    assert all("empty-trash" not in args for args, _json in cli.calls)
    live = ProtonDriveCli()
    proc = subprocess.run(
        [live.binary, "filesystem", "delete", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    text = f"{proc.stdout}\n{proc.stderr}".lower()
    assert "filesystem delete" in text
    assert "trashed" in text
    assert "permanently" in text
    print("delete help ok; per-item delete is distinct from empty-trash")


def test_live_permanent_delete() -> None:
    cli = ProtonDriveCli()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    name = f"pdl-del-{stamp}"
    my_path = join_path("/my-files", name)
    trash_path = join_path("/trash", name)
    before = {node_name(n) for n in cli.list("/trash")}
    try:
        cli.mkdir("/my-files", name)
        names = {node_name(n) for n in cli.list("/my-files")}
        assert name in names
        cli.trash(my_path)
        trash_names = {node_name(n) for n in cli.list("/trash")}
        assert name in trash_names
        cli.delete(trash_path)
        after = {node_name(n) for n in cli.list("/trash")}
        assert name not in after
        for existing in before:
            assert existing in after, existing
        print("permanent delete ok", name, "other trash kept", len(after))
    finally:
        try:
            live = cli.list("/my-files")
        except CliError:
            live = []
        for node in live:
            node_label = node_name(node)
            if node_label == name or node_label.startswith(f"pdl-del-{stamp}"):
                try:
                    cli.trash(join_path("/my-files", node_label))
                except CliError:
                    pass
        try:
            trash_nodes = cli.list("/trash")
        except CliError:
            trash_nodes = []
        for node in trash_nodes:
            node_label = node_name(node)
            if node_label == name or node_label.startswith(f"pdl-del-{stamp}"):
                try:
                    cli.delete(join_path("/trash", node_label))
                except CliError:
                    pass


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


def _offline_mode() -> bool:
    flag = os.environ.get("PROTON_DRIVE_OFFLINE", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    # GitHub Actions and other CI set CI=true; never hang on live Drive APIs there.
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    test_join_path()
    test_parse_version_latest()
    test_parse_version_newer()
    test_cli_help_exposes_storage_quota()
    test_parse_version_incomplete()
    test_parse_transfer_progress_lines()
    test_filesystem_mutate_commands()
    test_album_mutate_commands()
    test_invitation_helpers()
    if _offline_mode():
        print("offline mode: skipped live Proton CLI / API checks")
    else:
        test_live_cli_has_no_storage_quota_command()
        test_live_version_check()
        test_live_my_files()
        test_live_photos_timeline()
        test_live_album_management()
        test_live_sharing_and_invitations()
        test_empty_trash_help()
        test_delete_help_and_command()
        test_live_permanent_delete()
        test_live_rename_copy_move()
    print("all checks passed")
