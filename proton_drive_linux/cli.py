"""Thin wrapper around Proton's official `proton-drive` CLI (JSON mode)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import CLI_DOWNLOAD_URL


class CliError(RuntimeError):
    pass


_CLI_LINE = "Proton Drive CLI "
_SDK_LINE = "Proton Drive SDK "
_LATEST_LINE = "You are running the latest version."
_NEWER_RE = re.compile(
    r"A newer version is available:\s*(\d+\.\d+\.\d+)\s*\(you have\s*(\d+\.\d+\.\d+)\)",
    re.IGNORECASE,
)
_DOWNLOAD_RE = re.compile(r"Download at\s+(\S+)", re.IGNORECASE)
_SEMVER_RE = re.compile(r"^(\d+\.\d+\.\d+)")


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

    def upload(self, local_paths: list[str], parent: str) -> None:
        self.run(
            ["filesystem", "upload", *local_paths, parent, "-f", "skip", "-d", "merge", "-t"],
            json_out=False,
            timeout=3600,
        )

    def download(self, remote_path: str, local_folder: str) -> None:
        self.run(
            ["filesystem", "download", remote_path, local_folder, "-f", "skip", "-d", "merge"],
            json_out=False,
            timeout=3600,
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

    def photo_download(self, remote_path: str, local_folder: str) -> None:
        self.run(
            ["photo", "download", remote_path, local_folder, "-c", "rename"],
            json_out=False,
            timeout=3600,
        )

    def photo_upload(self, local_paths: list[str]) -> None:
        self.run(
            ["photo", "upload", *local_paths, "-c", "skip"],
            json_out=False,
            timeout=3600,
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
