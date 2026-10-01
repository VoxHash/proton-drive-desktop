#!/usr/bin/env python3
"""Offline checks for optional systemd --user sync service + timer units."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import paths  # noqa: E402
from proton_drive_desktop.sync import INTERVAL_SECONDS  # noqa: E402
from proton_drive_desktop import systemd_sync  # noqa: E402


def test_unit_names_and_paths() -> None:
    assert paths.SYNC_SYSTEMD_SERVICE == "proton-drive-desktop-sync.service"
    assert paths.SYNC_SYSTEMD_TIMER == "proton-drive-desktop-sync.timer"
    assert paths.SYNC_SYSTEMD_PATH == "proton-drive-desktop-sync.path"
    assert paths.sync_systemd_service_path().name == paths.SYNC_SYSTEMD_SERVICE
    assert paths.sync_systemd_timer_path().name == paths.SYNC_SYSTEMD_TIMER
    assert paths.sync_systemd_path_unit_path().name == paths.SYNC_SYSTEMD_PATH
    assert paths.systemd_user_dir().name == "user"
    assert paths.systemd_user_dir().parent.name == "systemd"


def test_render_service_unit_content() -> None:
    text = systemd_sync.render_sync_service_unit(
        python="/usr/bin/python3",
        root="/opt/proton-drive-desktop",
    )
    assert "[Unit]" in text
    assert "[Service]" in text
    assert "Type=oneshot" in text
    assert "Nice=10" in text
    assert "WorkingDirectory=/opt/proton-drive-desktop" in text
    assert 'Environment="PYTHONPATH=/opt/proton-drive-desktop"' in text
    assert "ExecStart=/usr/bin/python3 -m proton_drive_desktop.sync --once" in text
    assert "--force" not in text
    assert "WantedBy=default.target" in text
    assert "proton-drive-desktop" in text


def test_render_service_unit_quotes_spaced_paths() -> None:
    text = systemd_sync.render_sync_service_unit(
        python="/opt/My Python/bin/python3",
        root="/home/user/My Apps/proton-drive-desktop",
    )
    assert 'WorkingDirectory="/home/user/My Apps/proton-drive-desktop"' in text
    assert 'Environment="PYTHONPATH=/home/user/My Apps/proton-drive-desktop"' in text
    assert 'ExecStart="/opt/My Python/bin/python3" -m proton_drive_desktop.sync --once' in text


def test_render_timer_unit_uses_interval() -> None:
    text = systemd_sync.render_sync_timer_unit()
    assert "[Timer]" in text
    assert f"OnUnitActiveSec={INTERVAL_SECONDS}" in text
    assert INTERVAL_SECONDS == 300
    assert "OnBootSec=1min" in text
    assert "Persistent=true" in text
    assert f"Unit={paths.SYNC_SYSTEMD_SERVICE}" in text
    assert "WantedBy=timers.target" in text
    custom = systemd_sync.render_sync_timer_unit(interval_seconds=120)
    assert "OnUnitActiveSec=120" in custom
    clamped_low = systemd_sync.render_sync_timer_unit(interval_seconds=10)
    assert "OnUnitActiveSec=60" in clamped_low
    clamped_high = systemd_sync.render_sync_timer_unit(interval_seconds=999999)
    assert "OnUnitActiveSec=86400" in clamped_high


def test_write_and_remove_units(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-systemd-"))
    user_dir = base / "systemd" / "user"
    with mock.patch.object(systemd_sync, "systemd_user_dir", return_value=user_dir):
        with mock.patch.object(
            systemd_sync, "sync_systemd_service_path", return_value=user_dir / paths.SYNC_SYSTEMD_SERVICE
        ):
            with mock.patch.object(
                systemd_sync, "sync_systemd_timer_path", return_value=user_dir / paths.SYNC_SYSTEMD_TIMER
            ):
                service, timer = systemd_sync.write_sync_units(
                    python="/usr/bin/python3",
                    root=str(ROOT),
                )
                assert service.is_file()
                assert timer.is_file()
                service_text = service.read_text(encoding="utf-8")
                timer_text = timer.read_text(encoding="utf-8")
                assert "Type=oneshot" in service_text
                assert f"-m proton_drive_desktop.sync --once" in service_text
                assert f"OnUnitActiveSec={INTERVAL_SECONDS}" in timer_text
                systemd_sync.remove_sync_units()
                assert not service.is_file()
                assert not timer.is_file()


def test_set_sync_systemd_degrades_without_systemctl(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-systemd-off-"))
    user_dir = base / "systemd" / "user"
    with mock.patch.object(systemd_sync, "systemd_user_dir", return_value=user_dir):
        with mock.patch.object(
            systemd_sync, "sync_systemd_service_path", return_value=user_dir / paths.SYNC_SYSTEMD_SERVICE
        ):
            with mock.patch.object(
                systemd_sync, "sync_systemd_timer_path", return_value=user_dir / paths.SYNC_SYSTEMD_TIMER
            ):
                with mock.patch.object(systemd_sync, "systemd_user_available", return_value=False):
                    enabled = systemd_sync.set_sync_systemd(True, interval_seconds=180)
                    assert enabled["ok"] is False
                    assert enabled["available"] is False
                    assert (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()
                    assert (user_dir / paths.SYNC_SYSTEMD_TIMER).is_file()
                    timer_text = (user_dir / paths.SYNC_SYSTEMD_TIMER).read_text(encoding="utf-8")
                    assert "OnUnitActiveSec=180" in timer_text
                    disabled = systemd_sync.set_sync_systemd(False)
                    assert disabled["ok"] is True
                    assert not (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()
                    assert not (user_dir / paths.SYNC_SYSTEMD_TIMER).is_file()


def test_set_sync_systemd_calls_systemctl_when_available(tmp_path: Path | None = None) -> None:
    base = tmp_path or Path(tempfile.mkdtemp(prefix="pdd-systemd-on-"))
    user_dir = base / "systemd" / "user"
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
            systemd_sync, "sync_systemd_service_path", return_value=user_dir / paths.SYNC_SYSTEMD_SERVICE
        ):
            with mock.patch.object(
                systemd_sync, "sync_systemd_timer_path", return_value=user_dir / paths.SYNC_SYSTEMD_TIMER
            ):
                with mock.patch.object(systemd_sync, "systemd_user_available", return_value=True):
                    with mock.patch.object(systemd_sync, "_systemctl", side_effect=fake_systemctl):
                        result = systemd_sync.set_sync_systemd(True, interval_seconds=240)
                        assert result["ok"] is True
                        assert (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()
                        assert "OnUnitActiveSec=240" in (
                            user_dir / paths.SYNC_SYSTEMD_TIMER
                        ).read_text(encoding="utf-8")
                        assert ("daemon-reload",) in calls
                        assert ("enable", "--now", paths.SYNC_SYSTEMD_TIMER) in calls
                        calls.clear()
                        off = systemd_sync.set_sync_systemd(False)
                        assert off["ok"] is True
                        assert ("disable", "--now", paths.SYNC_SYSTEMD_TIMER) in calls
                        assert not (user_dir / paths.SYNC_SYSTEMD_SERVICE).is_file()


def test_settings_exposes_systemd_alongside_xdg() -> None:
    text = (ROOT / "proton_drive_desktop" / "app.py").read_text(encoding="utf-8")
    assert '_("systemd user timer")' in text
    assert "_on_systemd_sync" in text
    assert "set_sync_systemd" in text
    assert "systemd_user_available" in text
    assert "alongside XDG" in text or "alongside XDG autostart" in text
    assert '_("Start with this session")' in text
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert (
        "- [x] Optional systemd user unit for the sync worker alongside XDG autostart" in roadmap
    )
    assert (
        "- [x] Configurable sync interval in Settings (today fixed at 300s in `sync.py`)" in roadmap
    )
    assert '_("Sync interval (seconds)")' in text
    assert "_on_sync_interval" in text


def test_config_default_sync_systemd() -> None:
    from proton_drive_desktop import config

    assert "sync_systemd" in config._DEFAULTS
    assert config._DEFAULTS["sync_systemd"] is False
    assert config._DEFAULTS["sync_interval_seconds"] == 300
    assert config.normalize_sync_interval_seconds(15) == 60
    assert config.normalize_sync_interval_seconds(500) == 500


if __name__ == "__main__":
    test_unit_names_and_paths()
    test_render_service_unit_content()
    test_render_service_unit_quotes_spaced_paths()
    test_render_timer_unit_uses_interval()
    test_write_and_remove_units()
    test_set_sync_systemd_degrades_without_systemctl()
    test_set_sync_systemd_calls_systemctl_when_available()
    test_settings_exposes_systemd_alongside_xdg()
    test_config_default_sync_systemd()
    print("systemd sync checks passed")
