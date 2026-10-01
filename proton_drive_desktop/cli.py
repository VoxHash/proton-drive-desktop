"""Thin wrapper around Proton's official `proton-drive` CLI (JSON mode)."""

from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import CLI_DOWNLOAD_URL


class CliError(RuntimeError):
    pass


class TransferCancelled(CliError):
    """Raised when cancel_transfer() kills the active CLI process tree."""


def kill_owned_process_tree(pid: int, *, grace_seconds: float = 2.0) -> None:
    """SIGTERM then SIGKILL the process group for a Popen with start_new_session=True."""
    if pid <= 0:
        return

    def _signal_group(sig: int) -> None:
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    _signal_group(signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError, OSError):
            return
        time.sleep(0.05)
    _signal_group(signal.SIGKILL)


_CLI_LINE = "Proton Drive CLI "
_SDK_LINE = "Proton Drive SDK "
_LATEST_LINE = "You are running the latest version."
_NEWER_RE = re.compile(
    r"A newer version is available:\s*(\d+\.\d+\.\d+)\s*\(you have\s*(\d+\.\d+\.\d+)\)",
    re.IGNORECASE,
)
_DOWNLOAD_RE = re.compile(r"Download at\s+(\S+)", re.IGNORECASE)
_SEMVER_RE = re.compile(r"^(\d+\.\d+\.\d+)")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_PROGRESS_RE = re.compile(
    rf"^[{re.escape(_SPINNER_CHARS)}]?\s*(\d+(?:\.\d+)?)%\s+(.+?)\s+\(([^)]+)\)\s*$"
)
_QUEUE_RE = re.compile(
    r"^(?:ℹ\s*)?(Uploaded|Downloaded)\s+(\d+)\s*\|\s*Queued\s+(\d+)\s*$",
    re.IGNORECASE,
)
_SUMMARY_RE = re.compile(
    r"^\s*(Uploaded|Downloaded):\s+(.+)$",
    re.IGNORECASE,
)
_DONE_RE = re.compile(r"^[✅✔]\s*(.+?)\s*$")


@dataclass(frozen=True)
class TransferProgress:
    """Best-effort scrape of official CLI spinner / summary text (no JSON progress yet)."""

    percent: float | None = None
    name: str = ""
    size_label: str = ""
    completed: int | None = None
    queued: int | None = None
    direction: str = ""
    summary: str = ""
    raw: str = ""

    def status_text(self) -> str:
        if self.summary:
            return self.summary
        if self.percent is not None:
            bits: list[str] = []
            if self.name:
                bits.append(self.name)
            bits.append(f"{self.percent:.2f}%")
            if self.size_label:
                bits.append(f"({self.size_label})")
            return " — ".join(bits)
        if self.completed is not None and self.queued is not None:
            verb = "Uploaded" if self.direction != "download" else "Downloaded"
            return f"{verb} {self.completed} | Queued {self.queued}"
        if self.name:
            return self.name
        return self.raw or "Transferring…"


@dataclass(frozen=True)
class CliVersionInfo:
    """Parsed `proton-drive version` output (text; `-j` is ignored by CLI 0.8.0)."""

    raw: str
    app_version: str = ""
    sdk_version: str = ""
    cli_version: str = ""
    latest: bool = False
    update_available: bool = False
    newest_version: str = ""
    download_url: str = CLI_DOWNLOAD_URL
    status_line: str = ""

    def summary(self) -> str:
        if self.cli_version and self.update_available and self.newest_version:
            return f"CLI {self.cli_version} — {self.newest_version} available"
        if self.cli_version and self.latest:
            return f"CLI {self.cli_version} — latest"
        if self.cli_version:
            return f"CLI {self.cli_version}"
        first = self.raw.splitlines()[0] if self.raw else ""
        return first or "Official CLI"


def _semver_after_at(label: str) -> str:
    if "@" not in label:
        match = _SEMVER_RE.match(label.strip())
        return match.group(1) if match else ""
    match = _SEMVER_RE.match(label.split("@", 1)[1])
    return match.group(1) if match else ""


def parse_version_output(text: str) -> CliVersionInfo:
    """Parse live `proton-drive version` text. CLI 0.8.0 ignores `-j` for this command."""
    raw = (text or "").strip()
    payload = raw
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            app = str(data.get("appVersion") or "").strip()
            sdk = str(data.get("sdkVersion") or "").strip()
            rebuilt = [
                f"{_CLI_LINE}{app}" if app else "",
                f"{_SDK_LINE}{sdk}" if sdk else "",
            ]
            reconstructed = "\n".join(line for line in rebuilt if line)
            if reconstructed:
                payload = reconstructed
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    app_line = next((line for line in lines if line.startswith(_CLI_LINE)), "")
    sdk_line = next((line for line in lines if line.startswith(_SDK_LINE)), "")
    app_version = app_line[len(_CLI_LINE) :].strip() if app_line else ""
    sdk_version = sdk_line[len(_SDK_LINE) :].strip() if sdk_line else ""
    cli_version = _semver_after_at(app_version)
    latest = any(line == _LATEST_LINE for line in lines)
    newer_match = None
    for line in lines:
        found = _NEWER_RE.search(line)
        if found:
            newer_match = found
            break
    update_available = newer_match is not None
    newest_version = newer_match.group(1) if newer_match else (cli_version if latest else "")
    if newer_match and not cli_version:
        cli_version = newer_match.group(2)
    download_url = CLI_DOWNLOAD_URL
    for line in lines:
        found = _DOWNLOAD_RE.search(line)
        if found:
            download_url = found.group(1).rstrip(".,)")
            break
    if latest:
        status_line = _LATEST_LINE
    elif update_available:
        status_line = f"A newer version is available: {newest_version} (you have {cli_version})."
    else:
        status_line = "proton-drive version did not report latest or newer"
    return CliVersionInfo(
        raw=raw,
        app_version=app_version,
        sdk_version=sdk_version,
        cli_version=cli_version,
        latest=latest,
        update_available=update_available,
        newest_version=newest_version,
        download_url=download_url if update_available else CLI_DOWNLOAD_URL,
        status_line=status_line,
    )


# Top-level or account/auth subcommands that would advertise account storage quota.
_QUOTA_HELP_COMMANDS = frozenset({"quota", "storage", "usage"})
_QUOTA_HELP_PARENTS = frozenset({"account", "auth"})


def cli_help_exposes_storage_quota(help_text: str) -> bool:
    """True if live `proton-drive --help` lists an account/storage quota command.

    Matches indented usage lines only (skips the ``Usage:`` heading). CLI 0.8.0
    has no such command; rivals confirm the same. Never invents quota numbers.
    """
    for line in (help_text or "").splitlines():
        if not line.startswith("    "):
            continue
        parts = line.strip().lower().split()
        if not parts:
            continue
        if parts[0] in _QUOTA_HELP_COMMANDS:
            return True
        if (
            parts[0] in _QUOTA_HELP_PARENTS
            and len(parts) > 1
            and parts[1] in _QUOTA_HELP_COMMANDS | frozenset({"space", "quota"})
        ):
            return True
    return False


def strip_cli_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def parse_transfer_line(line: str) -> TransferProgress | None:
    """Parse one spinner / queue / summary line from `proton-drive` upload|download output."""
    cleaned = strip_cli_ansi(line).strip()
    if not cleaned or cleaned == "Transfer summary:":
        return None
    progress = _PROGRESS_RE.match(cleaned)
    if progress:
        return TransferProgress(
            percent=float(progress.group(1)),
            name=progress.group(2).strip(),
            size_label=progress.group(3).strip(),
            raw=cleaned,
        )
    queue = _QUEUE_RE.match(cleaned)
    if queue:
        direction = "upload" if queue.group(1).lower() == "uploaded" else "download"
        return TransferProgress(
            completed=int(queue.group(2)),
            queued=int(queue.group(3)),
            direction=direction,
            raw=cleaned,
        )
    summary = _SUMMARY_RE.match(cleaned)
    if summary:
        direction = "upload" if summary.group(1).lower() == "uploaded" else "download"
        detail = summary.group(2).strip()
        return TransferProgress(
            direction=direction,
            summary=f"{summary.group(1)}: {detail}",
            raw=cleaned,
        )
    done = _DONE_RE.match(cleaned)
    if done:
        return TransferProgress(name=done.group(1).strip(), percent=100.0, raw=cleaned)
    return None


def scrape_transfer_text(text: str) -> tuple[str, list[TransferProgress]]:
    """Split CR/LF CLI spinner stream; return leftover partial line and parsed events."""
    if not text:
        return "", []
    normalized = strip_cli_ansi(text).replace("\r\n", "\n").replace("\r", "\n")
    parts = normalized.split("\n")
    leftover = parts[-1]
    events: list[TransferProgress] = []
    for part in parts[:-1]:
        parsed = parse_transfer_line(part)
        if parsed is not None:
            events.append(parsed)
    return leftover, events


class NotLoggedIn(CliError):
    pass


def find_binary() -> str:
    env = os.environ.get("PROTON_DRIVE_BIN")
    if env and Path(env).is_file():
        return env
    try:
        from .config import load

        configured = str(load().get("cli_path") or "").strip()
        if configured and Path(configured).expanduser().is_file():
            return str(Path(configured).expanduser())
    except Exception:
        pass
    found = shutil.which("proton-drive")
    if found:
        return found
    home = Path.home() / ".local/bin/proton-drive"
    if home.is_file():
        return str(home)
    raise CliError("Official proton-drive CLI not found on PATH or ~/.local/bin")


def result_value(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("ok") and value.get("value"):
            return str(value["value"])
        err = value.get("error")
        if isinstance(err, dict):
            return str(err.get("name") or err.get("error") or "")
        if err:
            return str(err)
        nested = value.get("value")
        if isinstance(nested, str):
            return nested
        return ""
    if isinstance(value, str):
        return value
    return ""


def node_name(node: dict[str, Any]) -> str:
    name = result_value(node.get("name"))
    return name or "Unknown"


def invitation_uid(item: dict[str, Any]) -> str:
    return str(item.get("uid") or item.get("invitationUid") or "")


def invitation_name(item: dict[str, Any]) -> str:
    node = item.get("node")
    if isinstance(node, dict):
        name = node_name(node)
        if name != "Unknown":
            return name
    name = result_value(item.get("name"))
    if name:
        return name
    return str(item.get("inviteeEmail") or "Invitation")


def added_by_email(item: dict[str, Any]) -> str:
    return result_value(item.get("addedByEmail") or item.get("sharedBy") or "")


def member_email(item: dict[str, Any]) -> str:
    return str(item.get("inviteeEmail") or item.get("email") or added_by_email(item))


def member_role(item: dict[str, Any]) -> str:
    return str(item.get("role") or "viewer")


def node_size(node: dict[str, Any]) -> int | None:
    if node.get("type") not in ("file", "photo"):
        return None
    rev = node.get("activeRevision") or {}
    for key in ("claimedSize", "storageSize"):
        value = rev.get(key)
        if isinstance(value, int):
            return value
    value = node.get("totalStorageSize")
    return value if isinstance(value, int) else None


def escape_segment(name: str) -> str:
    return name.replace("\\", "\\\\").replace("/", "\\/")


def join_path(base: str, name: str) -> str:
    return base.rstrip("/") + "/" + escape_segment(name)


def album_cli_path(album: dict[str, Any]) -> str:
    raw = album.get("path")
    if isinstance(raw, str) and raw.startswith("/albums/") and raw != "/albums/":
        return raw
    name = node_name(album) if album.get("name") else ""
    if name and name != "Unknown":
        return join_path("/albums", name)
    uid = str(album.get("uid") or "")
    if uid:
        return join_path("/albums", uid)
    raise CliError("Album has no path, name, or UID")


def photo_cli_path(node: dict[str, Any], fallback: str = "") -> str:
    uid = str(node.get("uid") or node.get("nodeUid") or "")
    if uid:
        return f"/photos/{uid}"
    raw = node.get("path")
    if isinstance(raw, str) and raw.startswith("/photos/") and raw != "/photos/":
        return raw
    if fallback.startswith("/photos/") and fallback != "/photos/":
        return fallback
    raise CliError("Photo has no UID or path")


def account_email(nodes: list[dict[str, Any]]) -> str | None:
    for node in nodes:
        owned = node.get("ownedBy") or {}
        email = owned.get("email")
        if email:
            return str(email)
        author = node.get("keyAuthor") or {}
        if author.get("ok") and author.get("value"):
            return str(author["value"])
    return None


def format_size(num: int | None) -> str:
    if num is None:
        return "—"
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num} B"


class ProtonDriveCli:
    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or find_binary()
        self._transfer_proc: subprocess.Popen | None = None
        self._transfer_lock = threading.Lock()
        self._transfer_cancelled = False

    def cancel_transfer(self) -> bool:
        """Kill the owned process tree of the active upload/download. Returns True if signalled."""
        with self._transfer_lock:
            self._transfer_cancelled = True
            proc = self._transfer_proc
        if proc is None or proc.poll() is not None:
            return False
        kill_owned_process_tree(proc.pid)
        return True

    def run(self, args: list[str], *, json_out: bool = True, timeout: int = 180) -> Any:
        cmd = [self.binary, *args]
        if json_out:
            cmd.append("-j")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        combined = "\n".join(x for x in (stdout, stderr) if x)
        if proc.returncode != 0:
            if "need to login" in combined.lower():
                raise NotLoggedIn(combined)
            raise CliError(combined or f"proton-drive exited {proc.returncode}")
        if not json_out:
            return stdout
        if not stdout or stdout in ("undefined", "null"):
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CliError(f"Invalid JSON from proton-drive: {stdout[:400]}") from exc

    def run_transfer(
        self,
        args: list[str],
        *,
        timeout: int = 3600,
        on_progress: Callable[[TransferProgress], None] | None = None,
    ) -> str:
        """Run upload/download on a PTY so the CLI emits spinner progress text."""
        cmd = [self.binary, *args]
        master, slave = pty.openpty()
        output_chunks: list[str] = []
        leftover = ""
        with self._transfer_lock:
            self._transfer_cancelled = False
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            os.close(slave)
        with self._transfer_lock:
            self._transfer_proc = proc
            cancelled_at_start = self._transfer_cancelled

        deadline = time.monotonic() + timeout
        returncode = -1
        try:
            if cancelled_at_start:
                kill_owned_process_tree(proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                raise TransferCancelled("Transfer cancelled")
            while True:
                with self._transfer_lock:
                    cancelled = self._transfer_cancelled
                if cancelled:
                    kill_owned_process_tree(proc.pid)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    raise TransferCancelled("Transfer cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    kill_owned_process_tree(proc.pid)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    raise CliError("proton-drive transfer timed out")
                ready, _, _ = select.select([master], [], [], min(0.25, remaining))
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        chunk = b""
                    if chunk:
                        text = chunk.decode("utf-8", "replace")
                        output_chunks.append(text)
                        leftover, events = scrape_transfer_text(leftover + text)
                        if on_progress:
                            for event in events:
                                on_progress(event)
                        continue
                if proc.poll() is not None:
                    while True:
                        try:
                            more_ready, _, _ = select.select([master], [], [], 0)
                        except (ValueError, OSError):
                            break
                        if not more_ready:
                            break
                        try:
                            chunk = os.read(master, 4096)
                        except OSError:
                            break
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", "replace")
                        output_chunks.append(text)
                        leftover, events = scrape_transfer_text(leftover + text)
                        if on_progress:
                            for event in events:
                                on_progress(event)
                    if leftover and on_progress:
                        parsed = parse_transfer_line(leftover)
                        if parsed is not None:
                            on_progress(parsed)
                    break
            returncode = proc.wait(timeout=5)
        finally:
            with self._transfer_lock:
                if self._transfer_proc is proc:
                    self._transfer_proc = None
                was_cancelled = self._transfer_cancelled
                self._transfer_cancelled = False
            try:
                os.close(master)
            except OSError:
                pass

        if was_cancelled:
            raise TransferCancelled("Transfer cancelled")
        combined = strip_cli_ansi("".join(output_chunks)).strip()
        if returncode != 0:
            if "need to login" in combined.lower():
                raise NotLoggedIn(combined)
            raise CliError(combined or f"proton-drive exited {returncode}")
        return combined

    def version(self, *extra: str) -> str:
        proc = subprocess.run(
            [self.binary, "version", *extra],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return (proc.stdout or proc.stderr or "").strip()

    def version_info(self) -> CliVersionInfo:
        json_text = self.version("-j")
        info = parse_version_output(json_text)
        if info.cli_version or info.latest or info.update_available:
            return info
        return parse_version_output(self.version())

    def help_text(self) -> str:
        """Raw `proton-drive --help` (used to probe for quota / mount commands)."""
        proc = subprocess.run(
            [self.binary, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()

    def storage_quota_available(self) -> bool:
        """Whether the installed CLI advertises an account/storage quota command."""
        return cli_help_exposes_storage_quota(self.help_text())

    def list(self, path: str) -> list[dict[str, Any]]:
        data = self.run(["filesystem", "list", path])
        if data is None:
            return []
        if isinstance(data, list):
            return data
        raise CliError(f"Unexpected list payload for {path}")

    def login(self) -> None:
        proc = subprocess.run(
            [self.binary, "auth", "login"],
            check=False,
            timeout=600,
        )
        if proc.returncode != 0:
            raise CliError("Sign-in did not complete")

    def logout(self) -> None:
        self.run(["auth", "logout"], json_out=False)

    def mkdir(self, parent: str, name: str) -> None:
        self.run(["filesystem", "create-folder", parent, name], json_out=False)

    def trash(self, path: str) -> None:
        self.run(["filesystem", "trash", path], json_out=False)

    def restore(self, path: str) -> None:
        self.run(["filesystem", "restore", path], json_out=False)

    def delete(self, path: str) -> None:
        self.run(["filesystem", "delete", path], json_out=False)

    def rename(self, path: str, new_name: str) -> None:
        self.run(["filesystem", "rename", path, new_name], json_out=False)

    def copy(self, source_path: str, target_parent: str, *, name: str | None = None) -> None:
        args = ["filesystem", "copy"]
        if name:
            args.extend(["-n", name])
        args.extend([source_path, target_parent])
        self.run(args, json_out=False)

    def move(self, source_path: str, target_parent: str) -> None:
        self.run(["filesystem", "move", source_path, target_parent], json_out=False)

    def empty_trash(self) -> None:
        self.run(["filesystem", "empty-trash"], json_out=False)

    def upload(
        self,
        local_paths: list[str],
        parent: str,
        *,
        file_conflict: str = "skip",
        folder_conflict: str = "merge",
        on_progress: Callable[[TransferProgress], None] | None = None,
    ) -> None:
        # Official CLI: -f create-new-revision|rename|replace|skip; -d merge|rename|replace|skip
        self.run_transfer(
            [
                "filesystem",
                "upload",
                *local_paths,
                parent,
                "-f",
                file_conflict,
                "-d",
                folder_conflict,
                "-t",
            ],
            timeout=3600,
            on_progress=on_progress,
        )

    def download(
        self,
        remote_path: str,
        local_folder: str,
        *,
        file_conflict: str = "skip",
        folder_conflict: str = "merge",
        on_progress: Callable[[TransferProgress], None] | None = None,
    ) -> None:
        # Official CLI: -f rename|remove|skip; -d merge|rename|remove|skip
        self.run_transfer(
            [
                "filesystem",
                "download",
                remote_path,
                local_folder,
                "-f",
                file_conflict,
                "-d",
                folder_conflict,
            ],
            timeout=3600,
            on_progress=on_progress,
        )

    def info(self, path: str) -> dict[str, Any]:
        data = self.run(["filesystem", "info", path])
        if isinstance(data, dict):
            return data
        raise CliError(f"Unexpected info payload for {path}")

    def photo_timeline(self, load_details: bool = False) -> list[dict[str, Any]]:
        args = ["photo", "timeline"]
        if load_details:
            args.append("-d")
        data = self.run(args, timeout=300)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        raise CliError("Unexpected photo timeline payload")

    def album_list(self) -> list[dict[str, Any]]:
        data = self.run(["album", "list"])
        if data is None:
            return []
        if isinstance(data, list):
            return [item if isinstance(item, dict) else {"name": str(item)} for item in data]
        raise CliError("Unexpected album list payload")

    def album_photos(self, album_path: str, load_details: bool = True) -> list[dict[str, Any]]:
        args = ["album", "photos"]
        if load_details:
            args.append("-d")
        args.append(album_path)
        data = self.run(args, timeout=300)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        raise CliError(f"Unexpected album photos payload for {album_path}")

    def album_create(self, name: str) -> dict[str, Any] | None:
        data = self.run(["album", "create", name])
        if data is None:
            return None
        if isinstance(data, dict):
            return data
        raise CliError("Unexpected album create payload")

    def album_update(
        self,
        album_path: str,
        *,
        name: str | None = None,
        cover_photo_uid: str | None = None,
    ) -> dict[str, Any] | None:
        args = ["album", "update"]
        if name:
            args.extend(["-n", name])
        if cover_photo_uid:
            args.extend(["-c", cover_photo_uid])
        args.append(album_path)
        data = self.run(args)
        if data is None:
            return None
        if isinstance(data, dict):
            return data
        raise CliError(f"Unexpected album update payload for {album_path}")

    def album_delete(self, album_path: str, *, force: bool = False, save: bool = False) -> None:
        args = ["album", "delete"]
        if force:
            args.append("-f")
        if save:
            args.append("-s")
        args.append(album_path)
        self.run(args)

    def album_add_photo(self, album_path: str, photo_paths: list[str]) -> Any:
        return self.run(["album", "add-photo", album_path, *photo_paths])

    def album_remove_photo(self, album_path: str, photo_paths: list[str]) -> Any:
        return self.run(["album", "remove-photo", album_path, *photo_paths])

    def photo_download(
        self,
        remote_path: str,
        local_folder: str,
        *,
        on_progress: Callable[[TransferProgress], None] | None = None,
    ) -> None:
        self.run_transfer(
            ["photo", "download", remote_path, local_folder, "-c", "rename"],
            timeout=3600,
            on_progress=on_progress,
        )

    def photo_upload(
        self,
        local_paths: list[str],
        *,
        on_progress: Callable[[TransferProgress], None] | None = None,
    ) -> None:
        self.run_transfer(
            ["photo", "upload", *local_paths, "-c", "skip"],
            timeout=3600,
            on_progress=on_progress,
        )

    def sharing_status(self, path: str) -> dict[str, Any] | None:
        data = self.run(["sharing", "status", path])
        if data is None:
            return None
        if isinstance(data, dict):
            return data
        raise CliError(f"Unexpected sharing status payload for {path}")

    def sharing_invite(
        self,
        path: str,
        users: list[str],
        *,
        role: str = "viewer",
        message: str | None = None,
        include_node_name: bool = False,
    ) -> dict[str, Any] | None:
        args = ["sharing", "invite"]
        for user in users:
            args.extend(["-u", user])
        if role:
            args.extend(["-r", role])
        if message:
            args.extend(["-m", message])
        if include_node_name:
            args.append("-n")
        args.append(path)
        data = self.run(args)
        if data is None:
            return None
        if isinstance(data, dict):
            return data
        raise CliError(f"Unexpected sharing invite payload for {path}")

    def sharing_leave(self, path: str) -> None:
        self.run(["sharing", "leave", path], json_out=False)

    def sharing_remove(self, path: str, *, emails: list[str] | None = None, everyone: bool = False) -> None:
        args = ["sharing", "remove"]
        if everyone:
            args.append("-a")
        for email in emails or []:
            args.extend(["-e", email])
        args.append(path)
        self.run(args, json_out=False)

    def sharing_set_url(
        self,
        path: str,
        *,
        role: str = "viewer",
        password: str | None = None,
        expiration: str | None = None,
    ) -> dict[str, Any] | None:
        args = ["sharing", "set-url", "--role", role]
        if password:
            args.extend(["--password", password])
        if expiration:
            args.extend(["--expiration", expiration])
        args.append(path)
        data = self.run(args)
        if data is None:
            return None
        if isinstance(data, dict):
            return data
        raise CliError(f"Unexpected sharing set-url payload for {path}")

    def sharing_remove_url(self, path: str) -> None:
        self.run(["sharing", "remove-url", path], json_out=False)

    def invitation_list(self) -> list[dict[str, Any]]:
        data = self.run(["invitation", "list"])
        if data is None:
            return []
        if isinstance(data, list):
            return [item if isinstance(item, dict) else {"uid": str(item)} for item in data]
        raise CliError("Unexpected invitation list payload")

    def invitation_accept(self, uid: str) -> None:
        self.run(["invitation", "accept", uid], json_out=False)

    def invitation_reject(self, uid: str) -> None:
        self.run(["invitation", "reject", uid], json_out=False)


def _self_check() -> None:
    cli = ProtonDriveCli()
    items = cli.list("/my-files")
    assert isinstance(items, list), "list did not return an array"
    names = [node_name(i) for i in items]
    assert names, "My files is empty or unreadable"
    print("ok", find_binary())
    info = cli.version_info()
    print("ok", info.summary())
    print("ok", info.status_line)
    print("ok", len(items), "items in /my-files")
    print("ok account", account_email(items) or "unknown")


if __name__ == "__main__":
    _self_check()
