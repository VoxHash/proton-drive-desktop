"""Thin wrapper around Proton's official `proton-drive` CLI (JSON mode)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class CliError(RuntimeError):
    pass


class NotLoggedIn(CliError):
    pass


def find_binary() -> str:
    env = os.environ.get("PROTON_DRIVE_BIN")
    if env and Path(env).is_file():
        return env
    found = shutil.which("proton-drive")
    if found:
        return found
    home = Path.home() / ".local/bin/proton-drive"
    if home.is_file():
        return str(home)
    raise CliError("Official proton-drive CLI not found on PATH or ~/.local/bin")


def node_name(node: dict[str, Any]) -> str:
    name = node.get("name")
    if isinstance(name, dict):
        if name.get("ok") and name.get("value"):
            return str(name["value"])
        return str(name.get("error") or "Unknown")
    if isinstance(name, str) and name:
        return name
    return "Unknown"


def node_size(node: dict[str, Any]) -> int | None:
    if node.get("type") != "file":
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
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CliError(f"Invalid JSON from proton-drive: {stdout[:400]}") from exc

    def version(self) -> str:
        proc = subprocess.run(
            [self.binary, "version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return (proc.stdout or proc.stderr or "").strip()

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


def _self_check() -> None:
    cli = ProtonDriveCli()
    items = cli.list("/my-files")
    assert isinstance(items, list), "list did not return an array"
    names = [node_name(i) for i in items]
    assert names, "My files is empty or unreadable"
    print("ok", find_binary())
    print("ok", cli.version().splitlines()[0])
    print("ok", len(items), "items in /my-files")
    print("ok account", account_email(items) or "unknown")


if __name__ == "__main__":
    _self_check()
