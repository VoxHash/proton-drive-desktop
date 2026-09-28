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
    save_sync_status,
    sync_lock_path,
)
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
        return _status(state="off", message="Always-on folder is disabled in Settings")
    if gui_is_busy() and not force:
        return _status(state="idle", message="Waiting until the file list is idle")
    folder = Path(str(cfg.get("sync_folder") or default_sync_folder())).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock()
    if lock is None:
        return _status(state="running", message="Another sync pass is already running")
    errors: list[str] = []
    pulled = 0
    pushed = 0
    try:
        _status(
            state="running",
            last_started=utc_now(),
            last_error="",
            message=f"Syncing /my-files with {folder}",
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
        message = f"Synced {pulled} remote and {pushed} local item(s) with {folder}"
        if errors:
            message = f"{message}; {len(errors)} error(s)"
        return _status(
            state="error" if errors else "idle",
            last_finished=utc_now(),
            last_error="\n".join(errors)[:2000],
            last_pull=pulled,
            last_push=pushed,
            message=message,
        )
    except Exception as exc:  # noqa: BLE001 — persist the failure for Settings
        return _status(
            state="error",
            last_finished=utc_now(),
            last_error=str(exc)[:2000],
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
    payload = status if status is not None else load_sync_status()
    finished = str(payload.get("last_finished") or "").strip()
    if not finished:
        return True
    try:
        when = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return True
    age = datetime.now(timezone.utc) - when.astimezone(timezone.utc)
    return age.total_seconds() >= INTERVAL_SECONDS


def format_status_line(status: dict[str, Any] | None = None) -> str:
    cfg = load_config()
    if not cfg.get("sync_enabled"):
        return "Always-on folder: off"
    payload = status if status is not None else load_sync_status()
    state = str(payload.get("state") or "idle")
    message = str(payload.get("message") or "")
    if state == "running":
        return message or "Always-on folder: running"
    if state == "error":
        err = str(payload.get("last_error") or message or "error")
        return f"Always-on folder: {err[:80]}"
    finished = str(payload.get("last_finished") or "")
    if finished:
        return f"Always-on folder: last {finished}"
    return message or "Always-on folder: waiting"


def main(argv: list[str] | None = None) -> int:
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
