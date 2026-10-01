#!/usr/bin/env python3
"""Desktop notify-send helpers for always-on worker / auth expiry."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import config  # noqa: E402
from proton_drive_desktop import notify  # noqa: E402


def test_fingerprint_and_auth_detection() -> None:
    assert notify.notification_fingerprint("worker", "download a: timeout\nupload b: 422") == "worker:download a: timeout"
    assert notify.is_auth_failure("Error: You need to login")
    assert notify.is_auth_failure("Not logged in")
    assert not notify.is_auth_failure("download notes.txt: HTTP 422")
    print("fingerprint ok")


def test_debounce_coalesces_same_failure(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-notify-debounce")
    folder.mkdir(parents=True, exist_ok=True)
    original_dir = config.CONFIG_DIR
    config.CONFIG_DIR = folder
    try:
        detail = "upload secret.txt: HTTP 422"
        assert notify.should_notify("worker", detail)
        notify.mark_notified("worker", detail)
        assert not notify.should_notify("worker", detail, debounce_seconds=900)
        assert notify.should_notify("worker", "other error", debounce_seconds=900)
        assert notify.should_notify("auth", detail, debounce_seconds=900)
        notify.clear_notify_state()
        assert notify.should_notify("worker", detail, debounce_seconds=900)
        # Expired debounce window allows a repeat of the same key.
        notify.mark_notified("worker", detail)
        state = notify._load_state()
        notify._save_state(state["key"], "2020-01-01T00:00:00+00:00")
        assert notify.should_notify("worker", detail, debounce_seconds=900)
    finally:
        config.CONFIG_DIR = original_dir
    print("debounce ok")


def test_notify_worker_failure_calls_notify_send(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-notify-send")
    folder.mkdir(parents=True, exist_ok=True)
    original_dir = config.CONFIG_DIR
    config.CONFIG_DIR = folder
    calls: list[tuple] = []

    def fake_send(summary: str, body: str = "", *, urgency: str = "normal", icon: str | None = None) -> bool:
        calls.append((summary, body, urgency))
        return True

    try:
        with mock.patch.object(notify, "notify_send", side_effect=fake_send):
            assert notify.notify_worker_failure("download a: timeout")
            assert len(calls) == 1
            assert calls[0][0] == "Always-on folder failed"
            assert "download a: timeout" in calls[0][1]
            # Same failure within debounce window is skipped.
            assert not notify.notify_worker_failure("download a: timeout")
            assert len(calls) == 1
            notify.clear_notify_state()
            assert notify.notify_worker_failure("need to login before continuing", auth_expired=True)
            assert len(calls) == 2
            assert calls[1][0] == "Proton Drive session expired"
            assert calls[1][2] == "critical"
            # Auto-detect auth from CLI wording without auth_expired=True.
            notify.clear_notify_state()
            assert notify.notify_worker_failure("Error: You need to login")
            assert calls[-1][0] == "Proton Drive session expired"
    finally:
        config.CONFIG_DIR = original_dir
    print("notify_worker_failure ok")


def test_notify_send_invokes_binary() -> None:
    recorded: list[list[str]] = []

    class FakeProc:
        returncode = 0

    def fake_run(cmd, **_kwargs):
        recorded.append(list(cmd))
        return FakeProc()

    with mock.patch.object(notify.shutil, "which", return_value="/usr/bin/notify-send"):
        with mock.patch.object(notify.subprocess, "run", side_effect=fake_run):
            assert notify.notify_send("Summary", "Body", urgency="normal")
    assert recorded
    assert recorded[0][0] == "/usr/bin/notify-send"
    assert "--app-name=Proton Drive Desktop" in recorded[0]
    assert recorded[0][-2] == "Summary"
    assert recorded[0][-1] == "Body"
    with mock.patch.object(notify.shutil, "which", return_value=None):
        assert not notify.notify_send("Summary", "Body")
    print("notify-send argv ok")


def test_sync_hooks_notify() -> None:
    text = (ROOT / "proton_drive_desktop" / "sync.py").read_text(encoding="utf-8")
    assert "notify_worker_failure" in text
    assert "clear_notify_state" in text
    assert "NotLoggedIn" in text
    app = (ROOT / "proton_drive_desktop" / "app.py").read_text(encoding="utf-8")
    assert "notify_worker_failure" in app
    assert 'auth_expired=True' in app
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert "- [x] Desktop notifications (`notify-send`) when the always-on worker fails or auth expires" in roadmap
    print("hooks ok")


if __name__ == "__main__":
    test_fingerprint_and_auth_detection()
    test_debounce_coalesces_same_failure()
    test_notify_worker_failure_calls_notify_send()
    test_notify_send_invokes_binary()
    test_sync_hooks_notify()
    print("notify checks passed")
