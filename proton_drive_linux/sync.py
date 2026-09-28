"""Always-on local My files folder backed by the official CLI.

Live `proton-drive --help` (0.8.0) and ProtonDriveApps/sdk CLI have no mount,
FUSE, watch, or daemon command. This worker is the honest substitute: skip/merge
download of `/my-files` into a user folder, then skip/merge upload of that
folder's children. It runs as a separate niced process so GUI `filesystem list`
is not blocked on the GTK thread.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cli import CliError, ProtonDriveCli, join_path, node_name
from .config import (
    default_sync_folder,
    gui_is_busy,
    load as load_config,
    load_sync_status,
    parse_sync_status,
    save_sync_status,
    sync_lock_path,
)
from .i18n import _, ngettext
from .paths import repo_root

REMOTE_ROOT = "/my-files"
INTERVAL_SECONDS = 300


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_children(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    children: list[Path] = []
    for child in sorted(folder.iterdir(), key=lambda path: path.name.lower()):
        if child.name.startswith("."):
            continue
        children.append(child)
    return children


def _status(**updates: Any) -> dict[str, Any]:
    payload = load_sync_status()
    payload.update(updates)
    save_sync_status(payload)
    return payload


def _acquire_lock():
    path = sync_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def run_once(*, force: bool = False) -> dict[str, Any]:
    try:
        os.nice(10)
    except OSError:
        pass
    cfg = load_config()
    enabled = bool(cfg.get("sync_enabled"))
    if not enabled and not force:
        return _status(state="off", pid=0, message=_("Always-on folder is disabled in Settings"))
    if gui_is_busy() and not force:
        return _status(state="idle", message=_("Waiting until the file list is idle"))
    folder = Path(str(cfg.get("sync_folder") or default_sync_folder())).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock()
    if lock is None:
        holder = lock_holder_pid()
        return _status(
            state="running",
            pid=holder,
            message=_("Another sync pass is already running"),
        )
    errors: list[str] = []
    pulled = 0
    pushed = 0
    try:
        _status(
            state="running",
            last_started=utc_now(),
            pid=os.getpid(),
            message=_("Syncing /my-files with {folder}").format(folder=folder),
        )
        cli = ProtonDriveCli()
        nodes = cli.list(REMOTE_ROOT)
        for node in nodes:
            name = node_name(node)
            remote = join_path(REMOTE_ROOT, name)
            try:
                cli.download(remote, str(folder))
                pulled += 1
            except CliError as exc:
                errors.append(f"download {name}: {exc}")
        for child in local_children(folder):
            try:
                cli.upload([str(child)], REMOTE_ROOT)
                pushed += 1
            except CliError as exc:
                errors.append(f"upload {child.name}: {exc}")
        message = ngettext(
            "Synced {pulled} remote and {pushed} local item with {folder}",
            "Synced {pulled} remote and {pushed} local items with {folder}",
            pulled + pushed,
        ).format(pulled=pulled, pushed=pushed, folder=folder)
        if errors:
            message = _("{message}; {count} error(s)").format(message=message, count=len(errors))
        finished = utc_now()
        updates: dict[str, Any] = {
            "state": "error" if errors else "idle",
            "last_finished": finished,
            "last_error": "\n".join(errors)[:2000],
            "last_pull": pulled,
            "last_push": pushed,
            "pid": 0,
            "message": message,
        }
        if not errors:
            updates["last_success"] = finished
            updates["last_error"] = ""
        return _status(**updates)
    except Exception as exc:  # noqa: BLE001 — persist the failure for Settings
        return _status(
            state="error",
            last_finished=utc_now(),
            last_error=str(exc)[:2000],
            pid=0,
            message=str(exc)[:240],
        )
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def spawn_worker(*, force: bool = False) -> subprocess.Popen:
    env = os.environ.copy()
    root = str(repo_root())
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root if not previous else f"{root}{os.pathsep}{previous}"
    args = [sys.executable, "-m", "proton_drive_linux.sync", "--once"]
    if force:
        args.append("--force")

    def _lower_priority() -> None:
        try:
            os.nice(10)
        except OSError:
            pass

    return subprocess.Popen(
        args,
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        preexec_fn=_lower_priority,
    )


def due_for_pass(status: dict[str, Any] | None = None) -> bool:
    payload = parse_sync_status(status) if status is not None else load_sync_status()
    finished = str(payload.get("last_finished") or "").strip()
    if not finished:
        return True
    try:
        when = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - when.astimezone(timezone.utc)
    return age.total_seconds() >= INTERVAL_SECONDS


def lock_holder_pid() -> int:
    """PID of the process holding sync.lock, or 0 if no pass is running."""
    path = sync_lock_path()
    if not path.is_file():
        return 0
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return 0
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                handle.seek(0)
                pid = int(handle.read().strip() or "0")
            except (OSError, ValueError):
                return 1
            return pid if pid > 0 else 1
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return 0
    finally:
        handle.close()


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def format_when(iso: str) -> str:
    text = str(iso or "").strip()
    if not text:
        return _("Never")
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_files_last_pass(pull: int, push: int, *, had_pass: bool) -> str:
    if not had_pass:
        return _("No completed pass yet")
    return _("{pull} remote, {push} local copied").format(pull=pull, push=push)


def format_last_error(err: str) -> str:
    text = str(err or "").strip()
    if not text:
        return _("None")
    line = text.splitlines()[0].strip()
    if len(line) > 160:
        return f"{line[:157]}..."
    return line


def format_worker_line(*, enabled: bool, pid: int) -> str:
    if not enabled:
        return _("Off")
    if pid > 0:
        return _("Running (pid {pid})").format(pid=pid)
    return _("Stopped")


def activity_snapshot(status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Live always-on folder activity from the worker lock + XDG status file."""
    cfg = load_config()
    enabled = bool(cfg.get("sync_enabled"))
    payload = parse_sync_status(status) if status is not None else load_sync_status()
    pid = lock_holder_pid()
    if pid <= 0:
        stored = int(payload.get("pid") or 0)
        if _pid_is_alive(stored):
            pid = stored
    worker = format_worker_line(enabled=enabled, pid=pid)
    last_success = str(payload.get("last_success") or "").strip()
    last_finished = str(payload.get("last_finished") or "").strip()
    last_error = str(payload.get("last_error") or "").strip()
    pull = int(payload.get("last_pull") or 0)
    push = int(payload.get("last_push") or 0)
    had_pass = bool(last_finished)
    return {
        "enabled": enabled,
        "running": bool(enabled and pid > 0),
        "pid": pid if enabled else 0,
        "worker": worker,
        "state": str(payload.get("state") or ""),
        "message": str(payload.get("message") or ""),
        "last_success": format_when(last_success),
        "last_success_raw": last_success,
        "last_finished": format_when(last_finished),
        "last_finished_raw": last_finished,
        "last_error": format_last_error(last_error),
        "last_error_raw": last_error,
        "last_pull": pull,
        "last_push": push,
        "files": format_files_last_pass(pull, push, had_pass=had_pass),
    }


def mark_worker_stopped() -> dict[str, Any]:
    return _status(state="off", pid=0, message=_("Always-on folder is disabled in Settings"))


def mark_worker_idle() -> dict[str, Any]:
    cfg = load_config()
    if not cfg.get("sync_enabled"):
        return mark_worker_stopped()
    return _status(state="idle", pid=0, message=_("Always-on folder: waiting"))


def format_status_line(status: dict[str, Any] | None = None) -> str:
    snap = activity_snapshot(status)
    if not snap["enabled"]:
        return _("Always-on folder: off")
    if snap["running"]:
        return snap["message"] or _("Always-on folder: running (pid {pid})").format(pid=snap["pid"])
    err = str(snap.get("last_error_raw") or "").strip()
    if err:
        return _("Always-on folder: {error}").format(error=err[:80])
    finished = str(snap.get("last_success_raw") or snap.get("last_finished_raw") or "")
    if finished:
        return _("Always-on folder: last {when}").format(when=finished)
    return snap["message"] or _("Always-on folder: waiting")


def main(argv: list[str] | None = None) -> int:
    from .i18n import install as install_i18n

    install_i18n()
    parser = argparse.ArgumentParser(description="Official-CLI My files sync folder (not FUSE)")
    parser.add_argument("--once", action="store_true", help="Run one pull/push pass and exit")
    parser.add_argument("--force", action="store_true", help="Run even if the GUI is listing files")
    parser.add_argument("--status", action="store_true", help="Print the last sync status JSON")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.status:
        print(json.dumps(load_sync_status(), indent=2))
        return 0
    if args.once or args.force:
        result = run_once(force=args.force)
        print(result.get("message") or result.get("state") or "ok")
        return 1 if result.get("state") == "error" else 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
