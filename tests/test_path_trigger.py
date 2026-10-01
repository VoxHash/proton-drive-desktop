#!/usr/bin/env python3
"""Offline checks for optional local path trigger (stamp, debounce, systemd.path)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import config  # noqa: E402
from proton_drive_desktop import path_trigger  # noqa: E402
from proton_drive_desktop import paths  # noqa: E402
from proton_drive_desktop import systemd_sync  # noqa: E402
from proton_drive_desktop.sync import due_for_pass  # noqa: E402


def test_path_unit_name_and_paths() -> None:
    assert paths.SYNC_SYSTEMD_PATH == "proton-drive-desktop-sync.path"
    assert paths.sync_systemd_path_unit_path().name == paths.SYNC_SYSTEMD_PATH


def test_debounce_ready() -> None:
    assert path_trigger.debounce_ready(None, now_mono=100.0) is False
    assert path_trigger.debounce_ready(90.0, now_mono=100.0, debounce_seconds=15) is False
    assert path_trigger.debounce_ready(85.0, now_mono=100.0, debounce_seconds=15) is True
    assert path_trigger.debounce_ready(99.0, now_mono=100.0, debounce_seconds=0) is True
    assert path_trigger.PATH_TRIGGER_DEBOUNCE_SECONDS == 15


def test_request_stamp_and_due_for_pass(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-path-req-"))
    req = base / "sync-path-request"

    def _req_path() -> Path:
        return req

    with mock.patch.object(path_trigger, "sync_path_request_path", side_effect=_req_path):
        assert path_trigger.pass_request_pending() is False
        assert not due_for_pass(
            {"last_finished": "2099-01-01T00:00:00Z"},
            interval_seconds=300,
        )
        path_trigger.request_pass_soon()
        assert req.is_file()
        assert path_trigger.pass_request_pending() is True
        assert due_for_pass(
            {"last_finished": "2099-01-01T00:00:00Z"},
            interval_seconds=300,
        )
        path_trigger.clear_pass_request()
        assert not req.is_file()
        assert path_trigger.pass_request_pending() is False


def test_render_sync_path_unit() -> None:
    text = systemd_sync.render_sync_path_unit(folder="/home/user/Proton Drive")
    assert "[Path]" in text
    assert 'PathChanged="/home/user/Proton Drive"' in text
    assert 'PathModified="/home/user/Proton Drive"' in text
    assert "MakeDirectory=true" in text
    assert f"Unit={paths.SYNC_SYSTEMD_SERVICE}" in text
    assert "WantedBy=paths.target" in text
    plain = systemd_sync.render_sync_path_unit(folder="/tmp/pdrive-sync")
    assert "PathChanged=/tmp/pdrive-sync" in plain


def test_render_sync_path_unit_includes_child_dirs(
    tmp_path: Path | None = None,
) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-path-children-"))
    root = base / "sync-root"
    child = root / "Work"
    nested = child / "deep"
    root.mkdir(parents=True)
    child.mkdir()
    nested.mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    text = systemd_sync.render_sync_path_unit(folder=str(root))
    resolved_root = str(root.resolve())
    resolved_child = str(child.resolve())
    assert f"PathChanged={resolved_root}" in text or f'PathChanged="{resolved_root}"' in text
    assert f"PathChanged={resolved_child}" in text or f'PathChanged="{resolved_child}"' in text
    # Nested dirs are not watched (systemd path units are not recursive).
    assert str(nested.resolve()) not in text


def test_write_and_set_path_trigger_degrades(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-path-unit-"))
    user_dir = base / "systemd" / "user"
    folder = base / "sync-folder"
    folder.mkdir()
    with mock.patch.object(systemd_sync, "systemd_user_dir", return_value=user_dir):
        with mock.patch.object(
            systemd_sync,
            "sync_systemd_service_path",
            return_value=user_dir / paths.SYNC_SYSTEMD_SERVICE,
        ):
            with mock.patch.object(
                systemd_sync,
                "sync_systemd_timer_path",
                return_value=user_dir / paths.SYNC_SYSTEMD_TIMER,
            ):
                with mock.patch.object(
                    systemd_sync,
                    "sync_systemd_path_unit_path",
                    return_value=user_dir / paths.SYNC_SYSTEMD_PATH,
                ):
                    with mock.patch.object(
                        systemd_sync, "systemd_user_available", return_value=False
                    ):
                        result = systemd_sync.set_sync_path_trigger(
                            True, folder=str(folder)
                        )
                        assert result["ok"] is False
                        assert result["available"] is False
                        assert (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()
                        assert (user_dir / paths.SYNC_SYSTEMD_PATH).is_file()
                        path_text = (user_dir / paths.SYNC_SYSTEMD_PATH).read_text(
                            encoding="utf-8"
                        )
                        assert "PathChanged=" in path_text
                        assert str(folder.resolve()) in path_text.replace('"', "")
                        off = systemd_sync.set_sync_path_trigger(False)
                        assert off["ok"] is True
                        assert not (user_dir / paths.SYNC_SYSTEMD_PATH).is_file()
                        assert not (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()


def test_path_trigger_keeps_service_when_timer_present(
    tmp_path: Path | None = None,
) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-path-keep-"))
    user_dir = base / "systemd" / "user"
    folder = base / "folder"
    folder.mkdir()
    with mock.patch.object(systemd_sync, "systemd_user_dir", return_value=user_dir):
        with mock.patch.object(
            systemd_sync,
            "sync_systemd_service_path",
            return_value=user_dir / paths.SYNC_SYSTEMD_SERVICE,
        ):
            with mock.patch.object(
                systemd_sync,
                "sync_systemd_timer_path",
                return_value=user_dir / paths.SYNC_SYSTEMD_TIMER,
            ):
                with mock.patch.object(
                    systemd_sync,
                    "sync_systemd_path_unit_path",
                    return_value=user_dir / paths.SYNC_SYSTEMD_PATH,
                ):
                    with mock.patch.object(
                        systemd_sync, "systemd_user_available", return_value=False
                    ):
                        systemd_sync.set_sync_systemd(True, interval_seconds=120)
                        systemd_sync.set_sync_path_trigger(True, folder=str(folder))
                        assert (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()
                        assert (user_dir / paths.SYNC_SYSTEMD_TIMER).is_file()
                        assert (user_dir / paths.SYNC_SYSTEMD_PATH).is_file()
                        systemd_sync.set_sync_path_trigger(False)
                        assert not (user_dir / paths.SYNC_SYSTEMD_PATH).is_file()
                        assert (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()
                        assert (user_dir / paths.SYNC_SYSTEMD_TIMER).is_file()
                        systemd_sync.set_sync_systemd(False)
                        assert not (user_dir / paths.SYNC_SYSTEMD_TIMER).is_file()
                        assert not (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()


def test_set_path_trigger_calls_systemctl(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-path-ctl-"))
    user_dir = base / "systemd" / "user"
    folder = base / "watched"
    folder.mkdir()
    calls: list[tuple[str, ...]] = []

    def fake_systemctl(*args: str, timeout: float = 30):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = "enabled\n"
            stderr = ""

        return Result()

    with mock.patch.object(systemd_sync, "systemd_user_dir", return_value=user_dir):
        with mock.patch.object(
            systemd_sync,
            "sync_systemd_service_path",
            return_value=user_dir / paths.SYNC_SYSTEMD_SERVICE,
        ):
            with mock.patch.object(
                systemd_sync,
                "sync_systemd_timer_path",
                return_value=user_dir / paths.SYNC_SYSTEMD_TIMER,
            ):
                with mock.patch.object(
                    systemd_sync,
                    "sync_systemd_path_unit_path",
                    return_value=user_dir / paths.SYNC_SYSTEMD_PATH,
                ):
                    with mock.patch.object(
                        systemd_sync, "systemd_user_available", return_value=True
                    ):
                        with mock.patch.object(
                            systemd_sync, "_systemctl", side_effect=fake_systemctl
                        ):
                            result = systemd_sync.set_sync_path_trigger(
                                True, folder=str(folder)
                            )
                            assert result["ok"] is True
                            assert ("enable", "--now", paths.SYNC_SYSTEMD_PATH) in calls
                            assert ("restart", paths.SYNC_SYSTEMD_PATH) in calls
                            calls.clear()
                            off = systemd_sync.set_sync_path_trigger(False)
                            assert off["ok"] is True
                            assert (
                                "disable",
                                "--now",
                                paths.SYNC_SYSTEMD_PATH,
                            ) in calls


def test_settings_and_config_expose_path_trigger() -> None:
    text = (ROOT / "proton_drive_desktop" / "app.py").read_text(encoding="utf-8")
    assert '_("Sync soon after local edits")' in text
    assert "_on_path_trigger" in text
    assert "set_sync_path_trigger" in text
    assert "refresh_path_trigger_watch" in text
    assert "GioTreeMonitor" in text
    assert "PATH_TRIGGER_DEBOUNCE_SECONDS" in text
    assert "immediate subfolders" in text or "immediate child" in text.lower()
    assert "sync_path_trigger" in config._DEFAULTS
    assert config._DEFAULTS["sync_path_trigger"] is False
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert (
        "- [x] Optional local path trigger (inotify or systemd path unit) to run a pass "
        "soon after edits under the always-on folder, not only on the fixed interval"
    ) in roadmap
    assert (
        '- [x] Seed / “assume already synced” on first enable'
        in roadmap
        or '- [x] Seed / "assume already synced" on first enable' in roadmap
    )


if __name__ == "__main__":
    test_path_unit_name_and_paths()
    test_debounce_ready()
    test_request_stamp_and_due_for_pass()
    test_render_sync_path_unit()
    test_render_sync_path_unit_includes_child_dirs()
    test_write_and_set_path_trigger_degrades()
    test_path_trigger_keeps_service_when_timer_present()
    test_set_path_trigger_calls_systemctl()
    test_settings_and_config_expose_path_trigger()
    print("path trigger checks passed")
