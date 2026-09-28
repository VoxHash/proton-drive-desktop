"""Local GUI settings (theme, language, download folder, CLI path, sync folder). Not a Proton API."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "proton-drive-linux"
CONFIG_PATH = CONFIG_DIR / "gui.json"
SYNC_STATUS_PATH = CONFIG_DIR / "sync-status.json"
SYNC_LOCK_PATH = CONFIG_DIR / "sync.lock"
GUI_BUSY_PATH = CONFIG_DIR / "gui-busy"

_SYNC_STATUS_DEFAULTS: dict[str, Any] = {
    "state": "idle",
    "message": "",
    "last_error": "",
    "last_started": "",
    "last_finished": "",
    "last_success": "",
    "last_pull": 0,
    "last_push": 0,
    "pid": 0,
}


def default_sync_folder() -> str:
    return str(Path.home() / "Proton Drive")


_DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "language": "system",
    "download_folder": str(Path.home() / "Downloads"),
    "cli_path": "",
    "autostart": False,
    "sync_folder": default_sync_folder(),
    "sync_enabled": False,
}


def load() -> dict[str, Any]:
    data = dict(_DEFAULTS)
    if not CONFIG_PATH.is_file():
        return data
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return data
    if isinstance(raw, dict):
        for key in _DEFAULTS:
            if key in raw and raw[key] is not None:
                data[key] = raw[key]
    folder = Path(str(data.get("download_folder") or "")).expanduser()
    if not folder.is_dir():
        data["download_folder"] = _DEFAULTS["download_folder"]
    sync = str(data.get("sync_folder") or "").strip()
    data["sync_folder"] = sync or default_sync_folder()
    data["sync_enabled"] = bool(data.get("sync_enabled"))
    language = str(data.get("language") or "system").strip().lower().replace("-", "_")
    if language in {"en", "en_us", "en_gb", "english"}:
        data["language"] = "en"
    else:
        data["language"] = "system"
    return data


def save(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(_DEFAULTS)
    payload.update(data)
    CONFIG_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def download_folder() -> Path:
    folder = Path(str(load().get("download_folder") or _DEFAULTS["download_folder"])).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def sync_folder() -> Path:
    folder = Path(str(load().get("sync_folder") or default_sync_folder())).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def sync_lock_path() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return SYNC_LOCK_PATH


def parse_sync_status(raw: Any) -> dict[str, Any]:
    """Normalize worker status JSON (XDG sync-status.json) into known fields."""
    data = dict(_SYNC_STATUS_DEFAULTS)
    payload: dict[str, Any]
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return data
        payload = loaded if isinstance(loaded, dict) else {}
    elif isinstance(raw, dict):
        payload = raw
    else:
        return data
    int_keys = {"last_pull", "last_push", "pid"}
    for key in _SYNC_STATUS_DEFAULTS:
        if key not in payload or payload[key] is None:
            continue
        if key in int_keys:
            try:
                data[key] = int(payload[key])
            except (TypeError, ValueError):
                data[key] = 0
        else:
            data[key] = str(payload[key])
    if not str(data.get("last_success") or "").strip():
        if not str(data.get("last_error") or "").strip() and str(data.get("last_finished") or "").strip():
            data["last_success"] = str(data["last_finished"])
    return data


def load_sync_status() -> dict[str, Any]:
    if not SYNC_STATUS_PATH.is_file():
        return parse_sync_status({})
    try:
        raw = SYNC_STATUS_PATH.read_text(encoding="utf-8")
    except OSError:
        return parse_sync_status({})
    return parse_sync_status(raw)


def save_sync_status(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = parse_sync_status(data)
    SYNC_STATUS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def set_gui_busy(busy: bool) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if busy:
        GUI_BUSY_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return
    try:
        if GUI_BUSY_PATH.is_file() and GUI_BUSY_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            GUI_BUSY_PATH.unlink()
    except OSError:
        pass


def gui_is_busy() -> bool:
    if not GUI_BUSY_PATH.is_file():
        return False
    try:
        pid = int(GUI_BUSY_PATH.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def apply_theme(theme: str | None = None) -> None:
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    name = (theme or load().get("theme") or "dark").lower()
    style = Adw.StyleManager.get_default()
    mapping = {
        "system": Adw.ColorScheme.DEFAULT,
        "light": Adw.ColorScheme.FORCE_LIGHT,
        "dark": Adw.ColorScheme.FORCE_DARK,
    }
    style.set_color_scheme(mapping.get(name, Adw.ColorScheme.FORCE_DARK))
