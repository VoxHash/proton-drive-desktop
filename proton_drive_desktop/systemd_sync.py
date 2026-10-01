"""Optional systemd --user service + timer + path unit for always-on sync.

Alongside XDG autostart (which launches the GUI). The timer runs
``python -m proton_drive_desktop.sync --once`` on the Settings interval
(``sync_interval_seconds`` in gui.json; default 300). The optional path
unit watches the always-on folder (``PathChanged`` / ``PathModified`` on
the root and immediate child directories — systemd has no recursive path
units) and starts the same oneshot service soon after edits. Deep nested
edits while the GUI is closed still rely on the fixed interval (or the
recursive Gio watch while the app runs). Prefer real ``systemctl --user``;
degrade when absent.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import default_sync_folder, load as load_config, normalize_sync_interval_seconds
from .paths import (
    SYNC_SYSTEMD_PATH,
    SYNC_SYSTEMD_SERVICE,
    SYNC_SYSTEMD_TIMER,
    repo_root,
    sync_systemd_path_unit_path,
    sync_systemd_service_path,
    sync_systemd_timer_path,
    systemd_user_dir,
)
from .sync import INTERVAL_SECONDS, configured_interval_seconds

# systemd.path cannot recurse; watch this many immediate child directories too.
_MAX_PATH_UNIT_CHILD_DIRS = 64


def _systemd_path_quote(value: str) -> str:
    """Quote a path for a systemd unit line when it contains whitespace or quotes."""
    if not value or any(ch in value for ch in ' \t\n"\\'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _immediate_child_dirs(
    root: Path,
    *,
    limit: int = _MAX_PATH_UNIT_CHILD_DIRS,
) -> list[Path]:
    """Resolved immediate child directories under ``root`` (capped, non-hidden)."""
    children: list[Path] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return children
    for entry in entries:
        if len(children) >= max(0, int(limit)):
            break
        try:
            if entry.name.startswith("."):
                continue
            if not entry.is_dir() or entry.is_symlink():
                continue
            children.append(entry.resolve())
        except OSError:
            continue
    return children


def render_sync_service_unit(
    *,
    python: str | None = None,
    root: str | Path | None = None,
) -> str:
    """Return the oneshot user service unit text for one sync pass."""
    exe = str(python if python is not None else sys.executable)
    work = str(Path(root if root is not None else repo_root()).resolve())
    # Whole Environment= value quoted so paths with spaces stay one assignment.
    env_line = f'Environment="PYTHONPATH={work.replace(chr(34), "")}"'
    return "\n".join(
        [
            "[Unit]",
            "Description=Proton Drive Desktop always-on folder sync pass",
            "Documentation=https://github.com/VoxHash/proton-drive-desktop",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=oneshot",
            "Nice=10",
            f"WorkingDirectory={_systemd_path_quote(work)}",
            env_line,
            f"ExecStart={_systemd_path_quote(exe)} -m proton_drive_desktop.sync --once",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def render_sync_timer_unit(*, interval_seconds: int | None = None) -> str:
    """Return the user timer unit text (``OnUnitActiveSec`` from Settings interval)."""
    seconds = normalize_sync_interval_seconds(
        INTERVAL_SECONDS if interval_seconds is None else interval_seconds
    )
    return "\n".join(
        [
            "[Unit]",
            "Description=Proton Drive Desktop always-on folder sync timer",
            "Documentation=https://github.com/VoxHash/proton-drive-desktop",
            "",
            "[Timer]",
            "OnBootSec=1min",
            f"OnUnitActiveSec={seconds}",
            "AccuracySec=1min",
            "Persistent=true",
            f"Unit={SYNC_SYSTEMD_SERVICE}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def render_sync_path_unit(
    *,
    folder: str | Path | None = None,
    folders: list[str | Path] | None = None,
) -> str:
    """Return the user path unit text for always-on folder(s).

    systemd ``PathChanged`` / ``PathModified`` are not recursive. The unit
    watches each sync root plus up to ``_MAX_PATH_UNIT_CHILD_DIRS`` immediate
    child directories so one-level-deep edits still fire when the GUI is closed.
    Deeper trees need the GUI Gio watch or the fixed sync interval.
    """
    from .config import sync_pair_local_paths

    watch_paths: list[Path] = []
    if folders is not None:
        candidates = folders
    elif folder is not None:
        candidates = [folder]
    else:
        candidates = sync_pair_local_paths(enabled_only=True)
    seen: set[str] = set()
    for item in candidates:
        path = Path(item).expanduser()
        try:
            path = path.resolve()
        except OSError:
            path = path.absolute()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        watch_paths.append(path)
    if not watch_paths:
        watch_paths = [
            Path(load_config().get("sync_folder") or default_sync_folder()).expanduser()
        ]
    lines = [
        "[Unit]",
        "Description=Proton Drive Desktop always-on folder path trigger",
        "Documentation=https://github.com/VoxHash/proton-drive-desktop",
        "",
        "[Path]",
    ]
    for watch in watch_paths:
        lines.append(f"PathChanged={_systemd_path_quote(str(watch))}")
        lines.append(f"PathModified={_systemd_path_quote(str(watch))}")
        for child in _immediate_child_dirs(watch):
            quoted_child = _systemd_path_quote(str(child))
            lines.append(f"PathChanged={quoted_child}")
            lines.append(f"PathModified={quoted_child}")
    lines.extend(
        [
            "MakeDirectory=true",
            f"Unit={SYNC_SYSTEMD_SERVICE}",
            "",
            "[Install]",
            "WantedBy=paths.target",
            "",
        ]
    )
    return "\n".join(lines)


def write_sync_service_unit(
    *,
    python: str | None = None,
    root: str | Path | None = None,
) -> Path:
    """Write the oneshot service unit under ``~/.config/systemd/user/``."""
    directory = systemd_user_dir()
    directory.mkdir(parents=True, exist_ok=True)
    service = sync_systemd_service_path()
    service.write_text(
        render_sync_service_unit(python=python, root=root),
        encoding="utf-8",
    )
    return service


def write_sync_units(
    *,
    python: str | None = None,
    root: str | Path | None = None,
    interval_seconds: int | None = None,
) -> tuple[Path, Path]:
    """Write service + timer unit files under ``~/.config/systemd/user/``."""
    service = write_sync_service_unit(python=python, root=root)
    timer = sync_systemd_timer_path()
    timer.write_text(
        render_sync_timer_unit(interval_seconds=interval_seconds),
        encoding="utf-8",
    )
    return service, timer


def write_sync_path_unit(
    *,
    folder: str | Path | None = None,
    folders: list[str | Path] | None = None,
    python: str | None = None,
    root: str | Path | None = None,
) -> tuple[Path, Path]:
    """Write service + path unit files. Returns ``(service, path_unit)``."""
    service = write_sync_service_unit(python=python, root=root)
    path_unit = sync_systemd_path_unit_path()
    path_unit.parent.mkdir(parents=True, exist_ok=True)
    path_unit.write_text(
        render_sync_path_unit(folder=folder, folders=folders),
        encoding="utf-8",
    )
    return service, path_unit


def remove_sync_timer_unit() -> None:
    """Remove the timer unit file if present."""
    try:
        sync_systemd_timer_path().unlink(missing_ok=True)
    except OSError:
        pass


def remove_sync_path_unit_file() -> None:
    """Remove the path unit file if present."""
    try:
        sync_systemd_path_unit_path().unlink(missing_ok=True)
    except OSError:
        pass


def remove_sync_service_if_unused() -> None:
    """Remove the oneshot service when neither timer nor path unit remains."""
    if sync_systemd_timer_path().is_file() or sync_systemd_path_unit_path().is_file():
        return
    try:
        sync_systemd_service_path().unlink(missing_ok=True)
    except OSError:
        pass


def remove_sync_units() -> None:
    """Remove timer (+ service when unused). Kept for tests and callers."""
    remove_sync_timer_unit()
    remove_sync_service_if_unused()


def systemd_user_available() -> bool:
    """True when ``systemctl --user`` can talk to this session's user manager."""
    if not shutil.which("systemctl"):
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _systemctl(*args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def sync_timer_is_enabled() -> bool:
    """Whether the sync timer is enabled for this user (systemctl, else unit files)."""
    if systemd_user_available():
        try:
            result = _systemctl("is-enabled", SYNC_SYSTEMD_TIMER, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        state = (result.stdout or "").strip()
        return result.returncode == 0 and state in {"enabled", "enabled-runtime"}
    return sync_systemd_service_path().is_file() and sync_systemd_timer_path().is_file()


def sync_path_unit_is_enabled() -> bool:
    """Whether the sync path unit is enabled (systemctl, else unit file present)."""
    if systemd_user_available():
        try:
            result = _systemctl("is-enabled", SYNC_SYSTEMD_PATH, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        state = (result.stdout or "").strip()
        return result.returncode == 0 and state in {"enabled", "enabled-runtime"}
    return sync_systemd_path_unit_path().is_file() and sync_systemd_service_path().is_file()


def set_sync_systemd(
    enabled: bool,
    *,
    interval_seconds: int | None = None,
) -> dict[str, Any]:
    """Install/enable or disable/remove the user timer. Degrades without systemd.

    When enabling (or re-applying), ``OnUnitActiveSec`` uses ``interval_seconds``
    if given, otherwise the value from ``gui.json`` (default 300).

    Returns ``{"ok": bool, "message": str, "available": bool}``.
    """
    available = systemd_user_available()
    if enabled:
        seconds = (
            normalize_sync_interval_seconds(interval_seconds)
            if interval_seconds is not None
            else configured_interval_seconds()
        )
        write_sync_units(interval_seconds=seconds)
        if not available:
            return {
                "ok": False,
                "available": False,
                "message": "systemd --user is not available; wrote unit files only",
            }
        try:
            reload = _systemctl("daemon-reload")
            if reload.returncode != 0:
                detail = (reload.stderr or reload.stdout or "daemon-reload failed").strip()
                return {"ok": False, "available": True, "message": detail[:200]}
            enable = _systemctl("enable", "--now", SYNC_SYSTEMD_TIMER)
            if enable.returncode != 0:
                detail = (enable.stderr or enable.stdout or "enable failed").strip()
                return {"ok": False, "available": True, "message": detail[:200]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "available": True, "message": str(exc)[:200]}
        return {"ok": True, "available": True, "message": "enabled"}

    # Disable timer only; keep service if path unit still needs it.
    if available:
        try:
            _systemctl("disable", "--now", SYNC_SYSTEMD_TIMER)
            _systemctl("daemon-reload")
        except (OSError, subprocess.TimeoutExpired):
            pass
    remove_sync_timer_unit()
    remove_sync_service_if_unused()
    if available:
        try:
            _systemctl("daemon-reload")
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "ok": True,
        "available": available,
        "message": "disabled" if available else "removed unit files",
    }


def set_sync_path_trigger(
    enabled: bool,
    *,
    folder: str | Path | None = None,
    folders: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Install/enable or disable the user path unit. Degrades without systemd.

    Writes/reuses the oneshot sync service. Path watching covers each sync root
    and immediate child directories only (systemd has no recursive path units);
    the GUI adds recursive Gio/inotify when the app runs. Re-enabling rewrites
    and restarts the unit so a folder change takes effect.

    Returns ``{"ok": bool, "message": str, "available": bool}``.
    """
    available = systemd_user_available()
    watch_folders = folders
    if watch_folders is None and folder is not None:
        watch_folders = [folder]
    if watch_folders is None:
        from .config import sync_pair_local_paths

        watch_folders = sync_pair_local_paths(enabled_only=True)
    if enabled:
        write_sync_path_unit(folders=list(watch_folders))
        if not available:
            return {
                "ok": False,
                "available": False,
                "message": "systemd --user is not available; wrote path unit files only",
            }
        try:
            reload = _systemctl("daemon-reload")
            if reload.returncode != 0:
                detail = (reload.stderr or reload.stdout or "daemon-reload failed").strip()
                return {"ok": False, "available": True, "message": detail[:200]}
            enable = _systemctl("enable", "--now", SYNC_SYSTEMD_PATH)
            if enable.returncode != 0:
                detail = (enable.stderr or enable.stdout or "enable failed").strip()
                return {"ok": False, "available": True, "message": detail[:200]}
            # Restart so rewritten PathChanged= paths apply when already enabled.
            restart = _systemctl("restart", SYNC_SYSTEMD_PATH)
            if restart.returncode != 0:
                detail = (restart.stderr or restart.stdout or "restart failed").strip()
                return {"ok": False, "available": True, "message": detail[:200]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "available": True, "message": str(exc)[:200]}
        return {"ok": True, "available": True, "message": "enabled"}

    if available:
        try:
            _systemctl("disable", "--now", SYNC_SYSTEMD_PATH)
            _systemctl("daemon-reload")
        except (OSError, subprocess.TimeoutExpired):
            pass
    remove_sync_path_unit_file()
    remove_sync_service_if_unused()
    if available:
        try:
            _systemctl("daemon-reload")
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "ok": True,
        "available": available,
        "message": "disabled" if available else "removed path unit files",
    }
