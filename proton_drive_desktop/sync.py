"""Always-on local My files folder backed by the official CLI.

Live `proton-drive --help` (0.8.0) and ProtonDriveApps/sdk CLI have no mount,
FUSE, watch, or daemon command. This worker is the honest substitute: download
of `/my-files` into a user folder, then upload of that folder's children, using
the Settings conflict policy (default ``-f skip -d merge``; optional rename),
sync direction (bidirectional by default; upload-only or download-only), and
an optional per-pass timeout watchdog that cancels a hung CLI transfer.
It runs as a separate niced process so GUI `filesystem list` is not blocked on
the GTK thread.
"""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from .cli import (
    CliError,
    NotLoggedIn,
    ProtonDriveCli,
    TransferCancelled,
    join_path,
    node_name,
    node_size,
)
from .cli_verify import verify_proton_drive_binary
from .config import (
    SYNC_INTERVAL_SECONDS_DEFAULT,
    append_sync_activity_history,
    default_sync_folder,
    empty_sync_delta,
    enabled_sync_pairs,
    ensure_sync_pairs,
    gui_is_busy,
    load as load_config,
    load_sync_delta,
    load_sync_status,
    normalize_sync_conflict_policy,
    normalize_sync_direction,
    normalize_sync_interval_seconds,
    normalize_sync_pass_timeout_seconds,
    normalize_sync_remote_root,
    parse_sync_status,
    save_sync_delta,
    save_sync_status,
    sync_lock_path,
)
from .i18n import _, ngettext
from .notify import clear_notify_state, is_auth_failure, notify_send, notify_worker_failure
from .path_trigger import clear_pass_request, pass_request_pending
from .paths import repo_root

REMOTE_ROOT = "/my-files"
INTERVAL_SECONDS = SYNC_INTERVAL_SECONDS_DEFAULT

# Per CLI call during a sync pass (TrueNAS-style 3 tries; exponential backoff).
SYNC_RETRY_ATTEMPTS = 3
SYNC_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)

_T = TypeVar("_T")

# Remote already absent (idempotent trash / vanished download target).
_ALREADY_GONE_RE = re.compile(
    r"node not found|file or folder not found|does not exist|"
    r"no such (file|node|item)|trashed node not found|"
    r"path does not exist|code[=:\s]*2501",
    re.IGNORECASE,
)
# Remote already present (idempotent create-folder / skip-conflict upload).
_ALREADY_EXISTS_RE = re.compile(
    r"already exists|name already|duplicate|"
    r"with that name already exists|code[=:\s]*2500",
    re.IGNORECASE,
)
# Transient network / API glitches worth retrying (not auth, not validation).
_TRANSIENT_RE = re.compile(
    r"timed?\s*out|timeout|temporarily|please retry|try again|"
    r"connection reset|connection refused|connection aborted|"
    r"broken pipe|\beof\b|network is unreachable|temporary failure|"
    r"name resolution|dns (error|failure)|"
    r"\b429\b|\b502\b|\b503\b|\b504\b|"
    r"500 internal|service unavailable|"
    r"code[=:\s]*200501|"
    r"operation failed:\s*please retry",
    re.IGNORECASE,
)

# (negated, pattern) — negated True means gitignore-style !include
ExcludeRule = tuple[bool, str]


@dataclass(frozen=True)
class IdempotentResult:
    """CLI reported the desired end state already (no transfer needed)."""

    reason: str  # "already_gone" | "already_exists"


class PassTimedOut(CliError):
    """Raised when the optional per-pass watchdog fires (hung CLI / budget exceeded)."""


class PassWatchdog:
    """Daemon timer that cancels the owned CLI transfer when a pass exceeds its budget.

    TrueNAS-style optional ``--timeout``: off when *seconds* <= 0. On fire, calls
    *on_fire* (typically ``ProtonDriveCli.cancel_transfer``) so a hung PTY upload
    or download cannot block the worker forever.
    """

    def __init__(
        self,
        seconds: float,
        on_fire: Callable[[], Any] | None = None,
        *,
        message: str = "",
    ) -> None:
        self.seconds = max(0.0, float(seconds or 0.0))
        self._on_fire = on_fire
        self.message = message or f"Sync pass timed out after {int(self.seconds)}s"
        self.fired = threading.Event()
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        if self.seconds <= 0:
            return
        self._timer = threading.Timer(self.seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()

    def timed_out(self) -> bool:
        return self.fired.is_set()

    def check(self) -> None:
        if self.fired.is_set():
            raise PassTimedOut(self.message)

    def _fire(self) -> None:
        self.fired.set()
        callback = self._on_fire
        if callback is None:
            return
        try:
            callback()
        except Exception:  # noqa: BLE001 — never let the timer thread die on cancel noise
            pass


def is_already_gone_error(text: str) -> bool:
    """True when CLI output means the remote node is already absent."""
    return bool(_ALREADY_GONE_RE.search(str(text or "")))


def is_already_exists_error(text: str) -> bool:
    """True when CLI output means the remote name is already present."""
    return bool(_ALREADY_EXISTS_RE.search(str(text or "")))


def is_transient_cli_error(exc: BaseException | str) -> bool:
    """True for network / gateway / 'please retry' failures worth another attempt."""
    if isinstance(exc, (NotLoggedIn, TransferCancelled, PassTimedOut)):
        return False
    text = str(exc)
    if is_auth_failure(text):
        return False
    return bool(_TRANSIENT_RE.search(text))


def idempotent_cli_result(op: str, text: str) -> IdempotentResult | None:
    """Return an ``IdempotentResult`` when a failed CLI call is already done.

    Mirrors TrueNAS sync: trash/delete of a missing node, create-folder when
    the name exists, and upload/download skip-conflict 'already exists' /
    vanished-target 'not found' are treated as success (no destructive retry).
    """
    op_key = str(op or "").strip().lower()
    body = str(text or "")
    if op_key in ("trash", "delete") and is_already_gone_error(body):
        return IdempotentResult("already_gone")
    if op_key in ("create", "mkdir", "create-folder") and is_already_exists_error(body):
        return IdempotentResult("already_exists")
    if op_key in ("upload", "download") and is_already_exists_error(body):
        return IdempotentResult("already_exists")
    if op_key == "download" and is_already_gone_error(body):
        return IdempotentResult("already_gone")
    return None


def is_idempotent_cli_success(op: str, text: str) -> bool:
    """True when a failed CLI call already reached the desired end state."""
    return idempotent_cli_result(op, text) is not None


def call_with_retry(
    fn: Callable[[], _T],
    *,
    op: str = "",
    attempts: int = SYNC_RETRY_ATTEMPTS,
    backoff: tuple[float, ...] = SYNC_RETRY_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    abort: Callable[[], bool] | None = None,
) -> _T | IdempotentResult:
    """Run *fn* with exponential backoff on transient CLI/network errors.

    Auth failures (``NotLoggedIn`` / need to login), transfer cancels, and
    per-pass watchdog timeouts are never retried. Idempotent trash/create/
    upload/download end-states return ``IdempotentResult`` without raising
    (desired state already reached). Optional *abort* (e.g. watchdog
    ``timed_out``) stops between attempts so a fired pass budget cannot keep
    retrying.
    """
    max_attempts = max(1, int(attempts))
    delays = backoff if backoff else SYNC_RETRY_BACKOFF_SECONDS
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        if abort is not None and abort():
            raise PassTimedOut("Sync pass timed out")
        try:
            return fn()
        except NotLoggedIn:
            raise
        except PassTimedOut:
            raise
        except TransferCancelled:
            raise
        except CliError as exc:
            text = str(exc)
            if is_auth_failure(text):
                raise NotLoggedIn(text) from exc
            done = idempotent_cli_result(op, text)
            if done is not None:
                return done
            if not is_transient_cli_error(exc) or attempt >= max_attempts:
                raise
            delay = delays[min(attempt - 1, len(delays) - 1)]
            sleep(float(delay))
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise CliError(f"retry exhausted for {op or 'cli call'}")


def configured_remote_root(cfg: dict[str, Any] | None = None) -> str:
    """Remote Drive path for the always-on pass (``/my-files`` or a subtree)."""
    data = cfg if cfg is not None else load_config()
    return normalize_sync_remote_root(data.get("sync_remote_root"))


def sync_is_paused(cfg: dict[str, Any] | None = None) -> bool:
    """True when always-on is paused (Settings / tray); worker skips passes."""
    data = cfg if cfg is not None else load_config()
    return bool(data.get("sync_paused"))


def pairs_for_pass(cfg: dict[str, Any] | None = None, *, force: bool = False) -> list[dict[str, Any]]:
    """Enabled sync pairs for a worker pass (force ignores global sync_enabled)."""
    data = dict(cfg) if cfg is not None else load_config()
    if force and not bool(data.get("sync_enabled")):
        # Force from Sync now / preview path: still honor pair-level enable.
        return [pair for pair in ensure_sync_pairs(data) if bool(pair.get("enabled"))]
    return enabled_sync_pairs(data)

def conflict_cli_flags(policy: Any = None) -> tuple[str, str]:
    """Map Settings conflict policy to official CLI ``-f`` / ``-d`` values.

    Both upload and download share the safe pair used by this worker:

    * ``skip`` (default) → ``-f skip -d merge`` (leave existing files; merge folders)
    * ``rename`` → ``-f rename -d merge`` (unique suffix on conflicting files; merge folders)

    ``replace`` / ``remove`` / ``create-new-revision`` are not exposed: they are
    destructive or upload-only and are not part of this Settings control.
    """
    if normalize_sync_conflict_policy(policy) == "rename":
        return ("rename", "merge")
    return ("skip", "merge")


def configured_conflict_flags(cfg: dict[str, Any] | None = None) -> tuple[str, str]:
    """``(-f, -d)`` for the always-on pass from ``gui.json``."""
    data = cfg if cfg is not None else load_config()
    return conflict_cli_flags(data.get("sync_conflict_policy"))


def configured_interval_seconds(cfg: dict[str, Any] | None = None) -> int:
    """Always-on poll interval in seconds from ``gui.json`` (default 300)."""
    data = cfg if cfg is not None else load_config()
    return normalize_sync_interval_seconds(data.get("sync_interval_seconds"))


def configured_sync_direction(cfg: dict[str, Any] | None = None) -> str:
    """Always-on sync direction from ``gui.json`` (default ``bidirectional``)."""
    data = cfg if cfg is not None else load_config()
    return normalize_sync_direction(data.get("sync_direction"))


def configured_pass_timeout_seconds(cfg: dict[str, Any] | None = None) -> int:
    """Optional per-pass watchdog seconds from ``gui.json`` (``0`` = disabled)."""
    data = cfg if cfg is not None else load_config()
    return normalize_sync_pass_timeout_seconds(data.get("sync_pass_timeout_seconds"))


def direction_allows_download(direction: Any) -> bool:
    """True when a pass may list/download remote children."""
    return normalize_sync_direction(direction) in ("bidirectional", "download-only")


def direction_allows_upload(direction: Any) -> bool:
    """True when a pass may upload local children."""
    return normalize_sync_direction(direction) in ("bidirectional", "upload-only")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_exclude_patterns(raw: Any) -> list[ExcludeRule]:
    """Parse gitignore-style exclude text into ordered (negated, pattern) rules.

    Blank lines and ``#`` comments are ignored. Patterns may be separated by
    newlines or commas. A leading ``!`` negates (re-includes) a prior exclude.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        chunks = [str(item) for item in raw]
    else:
        text = str(raw).replace("\r\n", "\n").replace("\r", "\n").replace(",", "\n")
        chunks = text.split("\n")
    rules: list[ExcludeRule] = []
    for chunk in chunks:
        line = chunk.strip()
        if not line or line.startswith("#"):
            continue
        negated = False
        if line.startswith("!"):
            negated = True
            line = line[1:].strip()
            if not line:
                continue
        if line.startswith("/"):
            line = line[1:]
        if line.endswith("/") and len(line) > 1:
            line = line[:-1]
        rules.append((negated, line))
    return rules


def _name_matches_pattern(name: str, pattern: str) -> bool:
    """Match a top-level child name against one glob (gitignore-ish)."""
    if not pattern:
        return False
    candidate = name.strip().strip("/")
    if not candidate:
        return False
    if "/" not in pattern:
        return fnmatch.fnmatch(candidate, pattern)
    if fnmatch.fnmatch(candidate, pattern):
        return True
    # ``subdir/*.tmp`` style: also allow matching the basename segment
    return fnmatch.fnmatch(candidate, Path(pattern).name)


def is_excluded(name: str, rules: list[ExcludeRule] | None) -> bool:
    """Return True if *name* is excluded. Last matching rule wins (gitignore)."""
    if not rules:
        return False
    excluded = False
    matched = False
    for negated, pattern in rules:
        if not _name_matches_pattern(name, pattern):
            continue
        matched = True
        excluded = not negated
    return matched and excluded


def local_children(folder: Path, *, exclude_rules: list[ExcludeRule] | None = None) -> list[Path]:
    if not folder.is_dir():
        return []
    children: list[Path] = []
    for child in sorted(folder.iterdir(), key=lambda path: path.name.lower()):
        if child.name.startswith("."):
            continue
        if is_excluded(child.name, exclude_rules):
            continue
        children.append(child)
    return children


def _remote_item_size(node: dict[str, Any]) -> int | None:
    """Byte size from CLI list metadata (file/photo revision or folder total)."""
    size = node_size(node)
    if size is not None:
        return size
    value = node.get("totalStorageSize")
    return value if isinstance(value, int) else None


def local_fingerprint(path: Path) -> dict[str, Any] | None:
    """mtime/size fingerprint for a top-level sync child (file or directory tree)."""
    try:
        if path.is_file() and not path.is_symlink():
            st = path.stat()
            return {
                "local_mtime_ns": int(st.st_mtime_ns),
                "local_size": int(st.st_size),
                "local_is_dir": False,
                "local_file_count": 1,
            }
        if not path.is_dir():
            return None
    except OSError:
        return None
    total = 0
    max_mtime = 0
    count = 0
    try:
        max_mtime = int(path.stat().st_mtime_ns)
    except OSError:
        pass
    for root, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        try:
            max_mtime = max(max_mtime, int(Path(root).stat().st_mtime_ns))
        except OSError:
            pass
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            child = Path(root) / name
            try:
                st = child.stat()
            except OSError:
                continue
            total += int(st.st_size)
            max_mtime = max(max_mtime, int(st.st_mtime_ns))
            count += 1
    return {
        "local_mtime_ns": max_mtime,
        "local_size": total,
        "local_is_dir": True,
        "local_file_count": count,
    }


def remote_fingerprint(node: dict[str, Any]) -> dict[str, Any]:
    """mtime/size fingerprint from official CLI ``filesystem list`` node fields."""
    size = _remote_item_size(node)
    return {
        "remote_mtime": str(node.get("modificationTime") or ""),
        "remote_size": int(size) if size is not None else None,
        "remote_type": str(node.get("type") or ""),
    }


def _local_fp_matches(stored: dict[str, Any] | None, current: dict[str, Any] | None) -> bool:
    if not stored or not current:
        return False
    try:
        return (
            int(stored.get("local_mtime_ns")) == int(current.get("local_mtime_ns"))
            and int(stored.get("local_size")) == int(current.get("local_size"))
            and bool(stored.get("local_is_dir")) == bool(current.get("local_is_dir"))
            and int(stored.get("local_file_count") or 0) == int(current.get("local_file_count") or 0)
        )
    except (TypeError, ValueError):
        return False


def _remote_fp_matches(stored: dict[str, Any] | None, current: dict[str, Any] | None) -> bool:
    if not stored or not current:
        return False
    if str(stored.get("remote_mtime") or "") != str(current.get("remote_mtime") or ""):
        return False
    if str(stored.get("remote_type") or "") != str(current.get("remote_type") or ""):
        return False
    stored_size = stored.get("remote_size")
    current_size = current.get("remote_size")
    if stored_size is None and current_size is None:
        # Folders often omit size; mtime + type are enough when both lack size.
        return bool(str(stored.get("remote_mtime") or ""))
    try:
        return stored_size is not None and current_size is not None and int(stored_size) == int(current_size)
    except (TypeError, ValueError):
        return False


def ensure_sync_delta_scope(
    delta: dict[str, Any],
    *,
    folder: Path | str,
    remote_root: str,
    direction: str,
) -> dict[str, Any]:
    """Return delta state, resetting items when folder / remote root / direction changes."""
    folder_text = str(Path(folder).expanduser())
    remote_text = str(remote_root or REMOTE_ROOT)
    direction_text = normalize_sync_direction(direction)
    if (
        str(delta.get("folder") or "") != folder_text
        or str(delta.get("remote_root") or "") != remote_text
        or normalize_sync_direction(delta.get("direction")) != direction_text
    ):
        return empty_sync_delta(folder=folder_text, remote_root=remote_text, direction=direction_text)
    payload = dict(delta)
    payload["folder"] = folder_text
    payload["remote_root"] = remote_text
    payload["direction"] = direction_text
    if not isinstance(payload.get("items"), dict):
        payload["items"] = {}
    return payload


def _item_entry(items: dict[str, Any], name: str) -> dict[str, Any]:
    entry = items.get(name)
    return dict(entry) if isinstance(entry, dict) else {}


def _record_item(items: dict[str, Any], name: str, **fields: Any) -> None:
    entry = _item_entry(items, name)
    for key, value in fields.items():
        if value is None and key == "remote_size":
            entry[key] = None
        elif value is not None:
            entry[key] = value
    items[name] = entry


def should_skip_download(name: str, node: dict[str, Any], items: dict[str, Any]) -> bool:
    """True when remote mtime/size still matches the last successful sync of *name*."""
    return _remote_fp_matches(_item_entry(items, name), remote_fingerprint(node))


def should_skip_upload(path: Path, items: dict[str, Any]) -> bool:
    """True when local mtime/size still matches the last successful sync of this child."""
    return _local_fp_matches(_item_entry(items, path.name), local_fingerprint(path))


def preview_pass(
    *,
    cfg: dict[str, Any] | None = None,
    cli: ProtonDriveCli | None = None,
    folder: Path | str | None = None,
    remote_root: str | None = None,
    pair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Count would-be downloads and uploads without transferring or deleting.

    Uses a real ``filesystem list`` on the remote root and local directory
    children (respecting exclude rules and sync direction). Never calls
    download, upload, trash, or delete — this worker has no destructive-delete
    path. Upload-only skips the remote list; download-only skips local upload
    counts. Optional *pair* supplies per-pair local/remote/exclude/direction.
    """
    data = dict(cfg) if cfg is not None else load_config()
    pair_id = ""
    exclude_raw: Any = data.get("sync_exclude")
    direction_raw: Any = data.get("sync_direction")
    if pair is not None:
        pair_id = str(pair.get("id") or "")
        remote = (
            remote_root
            if remote_root is not None
            else normalize_sync_remote_root(pair.get("remote_root"))
        )
        local = Path(
            str(folder if folder is not None else pair.get("local_path") or default_sync_folder())
        ).expanduser()
        if "exclude" in pair:
            exclude_raw = pair.get("exclude")
        if "direction" in pair:
            direction_raw = pair.get("direction")
    else:
        remote = remote_root if remote_root is not None else configured_remote_root(data)
        local = Path(
            str(folder if folder is not None else data.get("sync_folder") or default_sync_folder())
        ).expanduser()
    exclude_rules = parse_exclude_patterns(exclude_raw)
    direction = normalize_sync_direction(direction_raw)
    driver = cli if cli is not None else ProtonDriveCli()
    delta = ensure_sync_delta_scope(
        load_sync_delta(pair_id or None),
        folder=local,
        remote_root=remote,
        direction=direction,
    )
    items = delta.get("items") if isinstance(delta.get("items"), dict) else {}
    download_names: list[str] = []
    skipped_downloads = 0
    if direction_allows_download(direction):
        for node in driver.list(remote):
            name = node_name(node)
            if not name or is_excluded(name, exclude_rules):
                continue
            if should_skip_download(name, node, items):
                skipped_downloads += 1
                continue
            download_names.append(name)
    upload_names: list[str] = []
    skipped_uploads = 0
    if direction_allows_upload(direction):
        for path in local_children(local, exclude_rules=exclude_rules):
            if should_skip_upload(path, items):
                skipped_uploads += 1
                continue
            upload_names.append(path.name)
    return {
        "remote_root": remote,
        "folder": str(local),
        "pair_id": pair_id,
        "sync_direction": direction,
        "download_count": len(download_names),
        "upload_count": len(upload_names),
        "download_names": download_names,
        "upload_names": upload_names,
        "skipped_download_count": skipped_downloads,
        "skipped_upload_count": skipped_uploads,
        "destructive_deletes": 0,
    }


def format_preview_message(preview: dict[str, Any], *, offer_seed: bool = False) -> str:
    """Human-readable dry-run summary for Settings dialogs."""
    downloads = int(preview.get("download_count") or 0)
    uploads = int(preview.get("upload_count") or 0)
    remote = str(preview.get("remote_root") or configured_remote_root())
    folder = str(preview.get("folder") or "")
    direction = normalize_sync_direction(preview.get("sync_direction"))
    if direction == "upload-only":
        direction_line = _("Direction: upload only (local → Drive)")
    elif direction == "download-only":
        direction_line = _("Direction: download only (Drive → local)")
    else:
        direction_line = _("Direction: bidirectional (download then upload)")
    lines: list[str] = []
    if direction_allows_download(direction):
        lines.append(
            ngettext(
                "Would download {count} remote item",
                "Would download {count} remote items",
                downloads,
            ).format(count=downloads)
        )
    if direction_allows_upload(direction):
        lines.append(
            ngettext(
                "Would upload {count} local item",
                "Would upload {count} local items",
                uploads,
            ).format(count=uploads)
        )
    transfer_lines = "\n".join(lines)
    body = _(
        "Preview only — nothing is transferred or deleted.\n\n"
        "Remote: {remote}\n"
        "Local: {folder}\n"
        "{direction_line}\n\n"
        "{transfer_lines}\n\n"
        "Existing files are never replaced. This worker never deletes."
    ).format(
        remote=remote,
        folder=folder,
        direction_line=direction_line,
        transfer_lines=transfer_lines,
    )
    if offer_seed:
        body = _(
            "{body}\n\n"
            "If both sides already match, choose Assume already synced to record "
            "current fingerprints and skip the initial bulk transfer (no upload or download)."
        ).format(body=body)
    return body


def seed_sync_delta(
    *,
    cfg: dict[str, Any] | None = None,
    cli: ProtonDriveCli | None = None,
    folder: Path | str | None = None,
    remote_root: str | None = None,
    pair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record current local+remote fingerprints into delta without transferring.

    Use when the user asserts both sides already match so the next pass skips
    the initial bulk upload/download. Uses the same ``filesystem list`` /
    fingerprint helpers as ``preview_pass`` and ``run_once`` — never calls
    download, upload, trash, or delete. Optional *pair* scopes delta by pair id.
    """
    data = dict(cfg) if cfg is not None else load_config()
    pair_id = ""
    exclude_raw: Any = data.get("sync_exclude")
    direction_raw: Any = data.get("sync_direction")
    if pair is not None:
        pair_id = str(pair.get("id") or "")
        remote = (
            remote_root
            if remote_root is not None
            else normalize_sync_remote_root(pair.get("remote_root"))
        )
        local = Path(
            str(folder if folder is not None else pair.get("local_path") or default_sync_folder())
        ).expanduser()
        if "exclude" in pair:
            exclude_raw = pair.get("exclude")
        if "direction" in pair:
            direction_raw = pair.get("direction")
    else:
        remote = remote_root if remote_root is not None else configured_remote_root(data)
        local = Path(
            str(folder if folder is not None else data.get("sync_folder") or default_sync_folder())
        ).expanduser()
        pairs = ensure_sync_pairs(data)
        if pairs:
            pair_id = str(pairs[0].get("id") or "")
    local.mkdir(parents=True, exist_ok=True)
    exclude_rules = parse_exclude_patterns(exclude_raw)
    direction = normalize_sync_direction(direction_raw)
    driver = cli if cli is not None else ProtonDriveCli()
    items: dict[str, Any] = {}
    remote_seeded = 0
    local_seeded = 0
    if direction_allows_download(direction):
        for node in driver.list(remote):
            name = node_name(node)
            if not name or is_excluded(name, exclude_rules):
                continue
            remote_fp = remote_fingerprint(node)
            local_fp = local_fingerprint(local / name) or {}
            _record_item(items, name, **remote_fp, **local_fp)
            remote_seeded += 1
    if direction_allows_upload(direction):
        for path in local_children(local, exclude_rules=exclude_rules):
            local_fp = local_fingerprint(path) or {}
            _record_item(items, path.name, **local_fp)
            local_seeded += 1
    delta = empty_sync_delta(folder=str(local), remote_root=remote, direction=direction)
    delta["items"] = items
    save_sync_delta(delta, pair_id or None)
    return {
        "remote_root": remote,
        "folder": str(local),
        "pair_id": pair_id,
        "sync_direction": direction,
        "remote_seeded": remote_seeded,
        "local_seeded": local_seeded,
        "item_count": len(items),
    }


def format_seed_message(result: dict[str, Any]) -> str:
    """Short toast/status line after seeding delta state."""
    count = int(result.get("item_count") or 0)
    return ngettext(
        "Recorded {count} item as already synced",
        "Recorded {count} items as already synced",
        count,
    ).format(count=count)


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


def _run_one_pair(
    cli: ProtonDriveCli,
    pair: dict[str, Any],
    *,
    watchdog: PassWatchdog,
    timeout_message: str,
) -> dict[str, Any]:
    """Sync one local↔remote pair. Returns counts and error lines (does not raise CliError)."""
    pair_id = str(pair.get("id") or "")
    folder = Path(str(pair.get("local_path") or default_sync_folder())).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    remote_root = normalize_sync_remote_root(pair.get("remote_root"))
    exclude_rules = parse_exclude_patterns(pair.get("exclude"))
    file_conflict, folder_conflict = conflict_cli_flags(pair.get("conflict_policy"))
    direction = normalize_sync_direction(pair.get("direction"))
    delta = ensure_sync_delta_scope(
        load_sync_delta(pair_id or None),
        folder=folder,
        remote_root=remote_root,
        direction=direction,
    )
    items: dict[str, Any] = dict(delta["items"]) if isinstance(delta.get("items"), dict) else {}
    pulled = 0
    pushed = 0
    skipped_pull = 0
    skipped_push = 0
    errors: list[str] = []
    abort = watchdog.timed_out
    label = f"{folder} ↔ {remote_root}"
    if direction_allows_download(direction):
        watchdog.check()
        listed = call_with_retry(
            lambda: cli.list(remote_root),
            op="list",
            abort=abort,
        )
        nodes: list[dict[str, Any]] = listed if isinstance(listed, list) else []
        for node in nodes:
            watchdog.check()
            name = node_name(node)
            if not name or is_excluded(name, exclude_rules):
                continue
            if should_skip_download(name, node, items):
                skipped_pull += 1
                continue
            remote = join_path(remote_root, name)
            try:
                outcome = call_with_retry(
                    lambda remote=remote: cli.download(
                        remote,
                        str(folder),
                        file_conflict=file_conflict,
                        folder_conflict=folder_conflict,
                    ),
                    op="download",
                    abort=abort,
                )
                if isinstance(outcome, IdempotentResult) and outcome.reason == "already_gone":
                    continue
                pulled += 1
                remote_fp = remote_fingerprint(node)
                local_fp = local_fingerprint(folder / name) or {}
                _record_item(items, name, **remote_fp, **local_fp)
            except NotLoggedIn:
                raise
            except TransferCancelled as exc:
                if watchdog.timed_out():
                    raise PassTimedOut(timeout_message) from exc
                raise
            except PassTimedOut:
                raise
            except CliError as exc:
                errors.append(f"download {name} ({label}): {exc}")
    if direction_allows_upload(direction):
        for child in local_children(folder, exclude_rules=exclude_rules):
            watchdog.check()
            if should_skip_upload(child, items):
                skipped_push += 1
                continue
            try:
                call_with_retry(
                    lambda child=child: cli.upload(
                        [str(child)],
                        remote_root,
                        file_conflict=file_conflict,
                        folder_conflict=folder_conflict,
                    ),
                    op="upload",
                    abort=abort,
                )
                pushed += 1
                local_fp = local_fingerprint(child) or {}
                _record_item(items, child.name, **local_fp)
            except NotLoggedIn:
                raise
            except TransferCancelled as exc:
                if watchdog.timed_out():
                    raise PassTimedOut(timeout_message) from exc
                raise
            except PassTimedOut:
                raise
            except CliError as exc:
                errors.append(f"upload {child.name} ({label}): {exc}")
    watchdog.check()
    delta["items"] = items
    save_sync_delta(delta, pair_id or None)
    return {
        "pair_id": pair_id,
        "folder": str(folder),
        "remote_root": remote_root,
        "pulled": pulled,
        "pushed": pushed,
        "skipped_pull": skipped_pull,
        "skipped_push": skipped_push,
        "errors": errors,
    }


def run_once(*, force: bool = False) -> dict[str, Any]:
    try:
        os.nice(10)
    except OSError:
        pass
    cfg = load_config()
    enabled = bool(cfg.get("sync_enabled"))
    if not enabled and not force:
        return _status(state="off", pid=0, message=_("Always-on folder is disabled in Settings"))
    if sync_is_paused(cfg) and not force:
        return _status(state="paused", pid=0, message=_("Always-on sync is paused"))
    if gui_is_busy() and not force:
        return _status(state="idle", message=_("Waiting until the file list is idle"))
    pairs = pairs_for_pass(cfg, force=force)
    if not pairs:
        return _status(
            state="idle" if enabled else "off",
            pid=0,
            message=_("No enabled sync pairs"),
        )
    for pair in pairs:
        Path(str(pair.get("local_path") or default_sync_folder())).expanduser().mkdir(
            parents=True, exist_ok=True
        )
    lock = _acquire_lock()
    if lock is None:
        holder = lock_holder_pid()
        return _status(
            state="running",
            pid=holder,
            message=_("Another sync pass is already running"),
        )
    clear_pass_request()
    errors: list[str] = []
    pulled = 0
    pushed = 0
    skipped_pull = 0
    skipped_push = 0
    timed_out = False
    pass_timeout = configured_pass_timeout_seconds(cfg)
    watchdog = PassWatchdog(0)
    try:
        checksum = verify_proton_drive_binary()
        if checksum.should_warn:
            notify_send(
                _("CLI checksum warning"),
                _(
                    "The proton-drive binary at {path} does not match any SHA-512 published by Proton "
                    "for Linux (digest {digest}…). This app will not replace it. Download a fresh CLI "
                    "from proton.me if you did not build it yourself."
                ).format(
                    path=checksum.path,
                    digest=(checksum.digest[:16] if checksum.digest else "?"),
                ),
                urgency="normal",
            )
        first = pairs[0]
        _status(
            state="running",
            last_started=utc_now(),
            pid=os.getpid(),
            message=_("Syncing {count} pair(s)").format(count=len(pairs))
            if len(pairs) > 1
            else _("Syncing {remote} with {folder}").format(
                remote=normalize_sync_remote_root(first.get("remote_root")),
                folder=first.get("local_path"),
            ),
        )
        cli = ProtonDriveCli()
        timeout_message = _("Sync pass timed out after {seconds}s").format(seconds=pass_timeout)
        cancel = getattr(cli, "cancel_transfer", None)
        watchdog = PassWatchdog(
            pass_timeout,
            cancel if callable(cancel) else None,
            message=timeout_message,
        )
        watchdog.start()
        for pair in pairs:
            result = _run_one_pair(
                cli,
                pair,
                watchdog=watchdog,
                timeout_message=timeout_message,
            )
            pulled += int(result.get("pulled") or 0)
            pushed += int(result.get("pushed") or 0)
            skipped_pull += int(result.get("skipped_pull") or 0)
            skipped_push += int(result.get("skipped_push") or 0)
            errors.extend(list(result.get("errors") or []))
        folder_note = pairs[0].get("local_path") if len(pairs) == 1 else _("{count} folders").format(count=len(pairs))
        message = ngettext(
            "Synced {pulled} remote and {pushed} local item with {folder}",
            "Synced {pulled} remote and {pushed} local items with {folder}",
            pulled + pushed,
        ).format(pulled=pulled, pushed=pushed, folder=folder_note)
        if skipped_pull or skipped_push:
            message = _(
                "{message}; skipped {skipped_pull} remote and {skipped_push} local unchanged"
            ).format(message=message, skipped_pull=skipped_pull, skipped_push=skipped_push)
        if errors:
            message = _("{message}; {count} error(s)").format(message=message, count=len(errors))
        finished = utc_now()
        updates: dict[str, Any] = {
            "state": "error" if errors else "idle",
            "last_finished": finished,
            "last_error": "\n".join(errors)[:2000],
            "last_pull": pulled,
            "last_push": pushed,
            "last_skipped_pull": skipped_pull,
            "last_skipped_push": skipped_push,
            "last_timeout": False,
            "last_pair_count": len(pairs),
            "pid": 0,
            "message": message,
        }
        if not errors:
            updates["last_success"] = finished
            updates["last_error"] = ""
            clear_notify_state()
        else:
            joined = "\n".join(errors)
            notify_worker_failure(joined, auth_expired=is_auth_failure(joined))
        status = append_sync_activity_history(
            {**load_sync_status(), **updates},
            finished=finished,
            pull=pulled,
            push=pushed,
            skipped_pull=skipped_pull,
            skipped_push=skipped_push,
            errors="\n".join(errors)[:2000],
            timeout=False,
            pair_count=len(pairs),
            message=message,
        )
        save_sync_status(status)
        return status
    except Exception as exc:  # noqa: BLE001 — persist the failure for Settings
        detail = str(exc)[:2000]
        timed_out = isinstance(exc, PassTimedOut)
        notify_worker_failure(detail, auth_expired=isinstance(exc, NotLoggedIn) or is_auth_failure(detail))
        finished = utc_now()
        updates = {
            "state": "error",
            "last_finished": finished,
            "last_error": detail,
            "last_pull": pulled,
            "last_push": pushed,
            "last_skipped_pull": skipped_pull,
            "last_skipped_push": skipped_push,
            "last_timeout": timed_out,
            "last_pair_count": len(pairs),
            "pid": 0,
            "message": str(exc)[:240],
        }
        status = append_sync_activity_history(
            {**load_sync_status(), **updates},
            finished=finished,
            pull=pulled,
            push=pushed,
            skipped_pull=skipped_pull,
            skipped_push=skipped_push,
            errors=detail,
            timeout=timed_out,
            pair_count=len(pairs),
            message=str(exc)[:240],
        )
        save_sync_status(status)
        return status
    finally:
        watchdog.stop()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def spawn_worker(*, force: bool = False) -> subprocess.Popen:
    env = os.environ.copy()
    root = str(repo_root())
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root if not previous else f"{root}{os.pathsep}{previous}"
    args = [sys.executable, "-m", "proton_drive_desktop.sync", "--once"]
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


def due_for_pass(
    status: dict[str, Any] | None = None,
    *,
    interval_seconds: int | None = None,
    cfg: dict[str, Any] | None = None,
) -> bool:
    data = cfg if cfg is not None else load_config()
    if sync_is_paused(data):
        return False
    if pass_request_pending():
        return True
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
    seconds = (
        normalize_sync_interval_seconds(interval_seconds)
        if interval_seconds is not None
        else configured_interval_seconds(data)
    )
    return age.total_seconds() >= seconds


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


def format_files_last_pass(
    pull: int,
    push: int,
    *,
    had_pass: bool,
    skipped_pull: int = 0,
    skipped_push: int = 0,
) -> str:
    if not had_pass:
        return _("No completed pass yet")
    line = _("{pull} remote, {push} local copied").format(pull=pull, push=push)
    if skipped_pull or skipped_push:
        line = _(
            "{line}; {skipped_pull} remote and {skipped_push} local skipped"
        ).format(line=line, skipped_pull=skipped_pull, skipped_push=skipped_push)
    return line


def format_last_error(err: str) -> str:
    text = str(err or "").strip()
    if not text:
        return _("None")
    line = text.splitlines()[0].strip()
    if len(line) > 160:
        return f"{line[:157]}..."
    return line


def format_worker_line(*, enabled: bool, pid: int, paused: bool = False) -> str:
    if not enabled:
        return _("Off")
    if paused:
        return _("Paused")
    if pid > 0:
        return _("Running (pid {pid})").format(pid=pid)
    return _("Stopped")


def format_activity_history_line(entry: dict[str, Any]) -> str:
    """One-line summary for Settings Activity history."""
    when = format_when(str(entry.get("finished") or ""))
    pull = int(entry.get("pull") or 0)
    push = int(entry.get("push") or 0)
    skipped_pull = int(entry.get("skipped_pull") or 0)
    skipped_push = int(entry.get("skipped_push") or 0)
    pair_count = int(entry.get("pair_count") or 0)
    errors = str(entry.get("errors") or "").strip()
    timeout = bool(entry.get("timeout"))
    parts = [
        when,
        _("{pull}↓ {push}↑").format(pull=pull, push=push),
    ]
    if skipped_pull or skipped_push:
        parts.append(
            _("skip {skipped_pull}/{skipped_push}").format(
                skipped_pull=skipped_pull, skipped_push=skipped_push
            )
        )
    if pair_count > 1:
        parts.append(_("{count} pairs").format(count=pair_count))
    if timeout:
        parts.append(_("timeout"))
    if errors:
        parts.append(_("error"))
    return " · ".join(parts)


def activity_snapshot(status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Live always-on folder activity from the worker lock + XDG status file."""
    cfg = load_config()
    enabled = bool(cfg.get("sync_enabled"))
    paused = bool(cfg.get("sync_paused"))
    payload = parse_sync_status(status) if status is not None else load_sync_status()
    pid = lock_holder_pid()
    if pid <= 0:
        stored = int(payload.get("pid") or 0)
        if _pid_is_alive(stored):
            pid = stored
    worker = format_worker_line(enabled=enabled, pid=pid, paused=paused)
    last_success = str(payload.get("last_success") or "").strip()
    last_finished = str(payload.get("last_finished") or "").strip()
    last_error = str(payload.get("last_error") or "").strip()
    pull = int(payload.get("last_pull") or 0)
    push = int(payload.get("last_push") or 0)
    skipped_pull = int(payload.get("last_skipped_pull") or 0)
    skipped_push = int(payload.get("last_skipped_push") or 0)
    had_pass = bool(last_finished)
    history = list(payload.get("history") or [])
    history_lines = [format_activity_history_line(entry) for entry in reversed(history[-20:])]
    return {
        "enabled": enabled,
        "paused": paused,
        "running": bool(enabled and not paused and pid > 0),
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
        "last_skipped_pull": skipped_pull,
        "last_skipped_push": skipped_push,
        "last_timeout": bool(payload.get("last_timeout")),
        "last_pair_count": int(payload.get("last_pair_count") or 0),
        "files": format_files_last_pass(
            pull,
            push,
            had_pass=had_pass,
            skipped_pull=skipped_pull,
            skipped_push=skipped_push,
        ),
        "history": history,
        "history_lines": history_lines,
    }


def mark_worker_stopped() -> dict[str, Any]:
    return _status(state="off", pid=0, message=_("Always-on folder is disabled in Settings"))


def mark_worker_idle() -> dict[str, Any]:
    cfg = load_config()
    if not cfg.get("sync_enabled"):
        return mark_worker_stopped()
    if sync_is_paused(cfg):
        return _status(state="paused", pid=0, message=_("Always-on sync is paused"))
    return _status(state="idle", pid=0, message=_("Always-on folder: waiting"))


def mark_worker_paused() -> dict[str, Any]:
    return _status(state="paused", pid=0, message=_("Always-on sync is paused"))


def format_status_line(status: dict[str, Any] | None = None) -> str:
    snap = activity_snapshot(status)
    if not snap["enabled"]:
        return _("Always-on folder: off")
    if snap.get("paused"):
        return _("Always-on sync: paused")
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
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Dry-run: list/count would-be downloads and uploads; no transfer or delete",
    )
    parser.add_argument("--status", action="store_true", help="Print the last sync status JSON")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.status:
        print(json.dumps(load_sync_status(), indent=2))
        return 0
    if args.preview:
        try:
            preview = preview_pass()
        except Exception as exc:  # noqa: BLE001 — CLI/auth failures print as JSON error
            print(json.dumps({"error": str(exc)[:2000]}, indent=2))
            return 1
        print(json.dumps(preview, indent=2))
        print(format_preview_message(preview), file=sys.stderr)
        return 0
    if args.once or args.force:
        result = run_once(force=args.force)
        print(result.get("message") or result.get("state") or "ok")
        return 1 if result.get("state") == "error" else 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
