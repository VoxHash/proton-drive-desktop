"""Local GUI settings (theme, language, download folder, CLI path, sync folder). Not a Proton API."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "proton-drive-desktop"
LEGACY_CONFIG_DIR = Path.home() / ".config" / "proton-drive-linux"
CONFIG_DIR = _DEFAULT_CONFIG_DIR
CONFIG_PATH = CONFIG_DIR / "gui.json"
SYNC_STATUS_PATH = CONFIG_DIR / "sync-status.json"
SYNC_DELTA_PATH = CONFIG_DIR / "sync-delta.json"
SYNC_LOCK_PATH = CONFIG_DIR / "sync.lock"
SYNC_PATH_REQUEST_PATH = CONFIG_DIR / "sync-path-request"
GUI_BUSY_PATH = CONFIG_DIR / "gui-busy"

_SYNC_DELTA_VERSION = 1
_SYNC_DELTA_STORE_VERSION = 2

_did_migrate_legacy = False

# Bounded always-on Activity history (last N completed passes).
SYNC_ACTIVITY_HISTORY_MAX = 20

_SYNC_STATUS_DEFAULTS: dict[str, Any] = {
    "state": "idle",
    "message": "",
    "last_error": "",
    "last_started": "",
    "last_finished": "",
    "last_success": "",
    "last_pull": 0,
    "last_push": 0,
    "last_skipped_pull": 0,
    "last_skipped_push": 0,
    "last_timeout": False,
    "last_pair_count": 0,
    "pid": 0,
    "history": [],
}


def default_sync_folder() -> str:
    return str(Path.home() / "Proton Drive")


def new_sync_pair_id() -> str:
    """Stable short id for a sync pair (stored in gui.json / delta store)."""
    return uuid.uuid4().hex[:12]


def empty_sync_pair(
    *,
    pair_id: str = "",
    local_path: str = "",
    remote_root: str = "/my-files",
    enabled: bool = True,
    exclude: str = "",
    conflict_policy: str = "skip",
    direction: str = "bidirectional",
) -> dict[str, Any]:
    """One local folder ↔ remote ``/my-files/...`` sync pair."""
    return {
        "id": str(pair_id or new_sync_pair_id()).strip() or new_sync_pair_id(),
        "enabled": bool(enabled),
        "local_path": str(local_path or default_sync_folder()).strip() or default_sync_folder(),
        "remote_root": normalize_sync_remote_root(remote_root),
        "exclude": _normalize_sync_exclude(exclude),
        "conflict_policy": normalize_sync_conflict_policy(conflict_policy),
        "direction": normalize_sync_direction(direction),
    }


def normalize_sync_pair(raw: Any) -> dict[str, Any] | None:
    """Normalize one pair dict; return None when unusable."""
    if not isinstance(raw, dict):
        return None
    local = str(raw.get("local_path") or raw.get("sync_folder") or "").strip()
    if not local:
        return None
    return empty_sync_pair(
        pair_id=str(raw.get("id") or "").strip(),
        local_path=local,
        remote_root=raw.get("remote_root") or raw.get("sync_remote_root") or "/my-files",
        enabled=bool(raw.get("enabled", True)),
        exclude=raw.get("exclude") if "exclude" in raw else raw.get("sync_exclude", ""),
        conflict_policy=raw.get("conflict_policy")
        if "conflict_policy" in raw
        else raw.get("sync_conflict_policy", "skip"),
        direction=raw.get("direction") if "direction" in raw else raw.get("sync_direction", "bidirectional"),
    )


def sync_pair_from_legacy(data: dict[str, Any], *, pair_id: str = "default") -> dict[str, Any]:
    """Build the first pair from pre-multi-folder ``sync_folder`` / ``sync_remote_root`` fields."""
    return empty_sync_pair(
        pair_id=pair_id or "default",
        local_path=str(data.get("sync_folder") or default_sync_folder()),
        remote_root=data.get("sync_remote_root") or "/my-files",
        enabled=True,
        exclude=data.get("sync_exclude") or "",
        conflict_policy=data.get("sync_conflict_policy") or "skip",
        direction=data.get("sync_direction") or "bidirectional",
    )


def ensure_sync_pairs(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized pairs; migrate legacy single-folder fields when ``sync_pairs`` is empty."""
    pairs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    raw_pairs = data.get("sync_pairs")
    if isinstance(raw_pairs, list):
        for item in raw_pairs:
            pair = normalize_sync_pair(item)
            if pair is None:
                continue
            if pair["id"] in seen_ids:
                pair["id"] = new_sync_pair_id()
            seen_ids.add(pair["id"])
            pairs.append(pair)
    if not pairs:
        pairs = [sync_pair_from_legacy(data, pair_id="default")]
    return pairs


def mirror_primary_pair_to_legacy(data: dict[str, Any], pairs: list[dict[str, Any]] | None = None) -> None:
    """Keep legacy single-folder keys aligned with the first pair (backward compatible)."""
    resolved = pairs if pairs is not None else ensure_sync_pairs(data)
    if not resolved:
        return
    primary = resolved[0]
    data["sync_folder"] = primary["local_path"]
    data["sync_remote_root"] = primary["remote_root"]
    data["sync_exclude"] = primary["exclude"]
    data["sync_conflict_policy"] = primary["conflict_policy"]
    data["sync_direction"] = primary["direction"]


def apply_legacy_sync_fields_to_primary(data: dict[str, Any], pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When Settings still writes ``sync_folder`` / friends, push those into pairs[0]."""
    if not pairs:
        return pairs
    primary = dict(pairs[0])
    if "sync_folder" in data and data.get("sync_folder") is not None:
        folder = str(data.get("sync_folder") or "").strip()
        if folder:
            primary["local_path"] = folder
    if "sync_remote_root" in data and data.get("sync_remote_root") is not None:
        primary["remote_root"] = normalize_sync_remote_root(data.get("sync_remote_root"))
    if "sync_exclude" in data and data.get("sync_exclude") is not None:
        primary["exclude"] = _normalize_sync_exclude(data.get("sync_exclude"))
    if "sync_conflict_policy" in data and data.get("sync_conflict_policy") is not None:
        primary["conflict_policy"] = normalize_sync_conflict_policy(data.get("sync_conflict_policy"))
    if "sync_direction" in data and data.get("sync_direction") is not None:
        primary["direction"] = normalize_sync_direction(data.get("sync_direction"))
    normalized = normalize_sync_pair(primary)
    pairs[0] = normalized if normalized is not None else primary
    return pairs


def enabled_sync_pairs(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Enabled pairs from config (pair-level ``enabled``); empty when always-on is off."""
    data = cfg if cfg is not None else load()
    if not bool(data.get("sync_enabled")):
        return []
    return [pair for pair in ensure_sync_pairs(data) if bool(pair.get("enabled"))]


def sync_pair_local_paths(cfg: dict[str, Any] | None = None, *, enabled_only: bool = True) -> list[str]:
    """Local folder paths for path-trigger / systemd watches."""
    data = cfg if cfg is not None else load()
    pairs = ensure_sync_pairs(data)
    paths: list[str] = []
    seen: set[str] = set()
    for pair in pairs:
        if enabled_only and not bool(pair.get("enabled")):
            continue
        path = str(Path(str(pair.get("local_path") or "")).expanduser())
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    if not paths:
        fallback = str(Path(str(data.get("sync_folder") or default_sync_folder())).expanduser())
        paths.append(fallback)
    return paths


_DEFAULT_WINDOW_WIDTH = 1180
_DEFAULT_WINDOW_HEIGHT = 760

_DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "language": "system",
    "download_folder": str(Path.home() / "Downloads"),
    "cli_path": "",
    "autostart": False,
    "sync_folder": default_sync_folder(),
    "sync_enabled": False,
    "sync_paused": False,
    "sync_exclude": "",
    "sync_remote_root": "/my-files",
    "sync_conflict_policy": "skip",
    "sync_direction": "bidirectional",
    "sync_interval_seconds": 300,
    "sync_pass_timeout_seconds": 0,
    "sync_systemd": False,
    "sync_path_trigger": False,
    "sync_pairs": [],
    "setup_completed": False,
    "view_mode": "list",
    "window_width": _DEFAULT_WINDOW_WIDTH,
    "window_height": _DEFAULT_WINDOW_HEIGHT,
    "window_maximized": False,
    "last_path": "/my-files",
}


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _merge_gui_settings(legacy: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Prefer current values; fill missing keys from legacy."""
    merged: dict[str, Any] = {}
    for key in _DEFAULTS:
        if key in current and current[key] is not None:
            merged[key] = current[key]
        elif key in legacy and legacy[key] is not None:
            merged[key] = legacy[key]
    return merged


def _maybe_migrate_legacy_config() -> None:
    """One-time copy/merge from ~/.config/proton-drive-linux into the desktop path."""
    global _did_migrate_legacy
    if _did_migrate_legacy:
        return
    _did_migrate_legacy = True
    try:
        if CONFIG_DIR.resolve() != _DEFAULT_CONFIG_DIR.resolve():
            return
    except OSError:
        return
    if not LEGACY_CONFIG_DIR.is_dir():
        return

    legacy_gui = LEGACY_CONFIG_DIR / "gui.json"
    legacy_sync = LEGACY_CONFIG_DIR / "sync-status.json"
    legacy_data = _read_json_object(legacy_gui)
    current_data = _read_json_object(CONFIG_PATH) or {}
    if legacy_data is not None:
        merged = _merge_gui_settings(legacy_data, current_data)
        if merged:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            payload = dict(_DEFAULTS)
            payload.update(merged)
            CONFIG_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            legacy_gui.unlink(missing_ok=True)
        except OSError:
            pass

    if legacy_sync.is_file() and not SYNC_STATUS_PATH.is_file():
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_sync, SYNC_STATUS_PATH)
            legacy_sync.unlink(missing_ok=True)
        except OSError:
            pass
    elif legacy_sync.is_file():
        try:
            legacy_sync.unlink(missing_ok=True)
        except OSError:
            pass

    for name in ("sync.lock", "gui-busy"):
        try:
            (LEGACY_CONFIG_DIR / name).unlink(missing_ok=True)
        except OSError:
            pass

    try:
        remaining = list(LEGACY_CONFIG_DIR.iterdir())
    except OSError:
        return
    if not remaining:
        try:
            LEGACY_CONFIG_DIR.rmdir()
        except OSError:
            pass


def load() -> dict[str, Any]:
    _maybe_migrate_legacy_config()
    data = dict(_DEFAULTS)
    if not CONFIG_PATH.is_file():
        pairs = ensure_sync_pairs(data)
        data["sync_pairs"] = pairs
        mirror_primary_pair_to_legacy(data, pairs)
        return data
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pairs = ensure_sync_pairs(data)
        data["sync_pairs"] = pairs
        mirror_primary_pair_to_legacy(data, pairs)
        return data
    if isinstance(raw, dict):
        for key in _DEFAULTS:
            if key in raw and raw[key] is not None:
                data[key] = raw[key]
        # Preserve sync_pairs list even when empty in file (migration fills it).
        if "sync_pairs" in raw:
            data["sync_pairs"] = raw["sync_pairs"]
    folder = Path(str(data.get("download_folder") or "")).expanduser()
    if not folder.is_dir():
        data["download_folder"] = _DEFAULTS["download_folder"]
    sync = str(data.get("sync_folder") or "").strip()
    data["sync_folder"] = sync or default_sync_folder()
    data["sync_enabled"] = bool(data.get("sync_enabled"))
    data["sync_paused"] = bool(data.get("sync_paused"))
    data["setup_completed"] = bool(data.get("setup_completed"))
    data["sync_exclude"] = _normalize_sync_exclude(data.get("sync_exclude"))
    data["sync_remote_root"] = normalize_sync_remote_root(data.get("sync_remote_root"))
    data["sync_conflict_policy"] = normalize_sync_conflict_policy(data.get("sync_conflict_policy"))
    data["sync_direction"] = normalize_sync_direction(data.get("sync_direction"))
    data["sync_interval_seconds"] = normalize_sync_interval_seconds(data.get("sync_interval_seconds"))
    data["sync_pass_timeout_seconds"] = normalize_sync_pass_timeout_seconds(
        data.get("sync_pass_timeout_seconds")
    )
    data["sync_systemd"] = bool(data.get("sync_systemd"))
    data["sync_path_trigger"] = bool(data.get("sync_path_trigger"))
    pairs = ensure_sync_pairs(data)
    data["sync_pairs"] = pairs
    mirror_primary_pair_to_legacy(data, pairs)
    mode = str(data.get("view_mode") or "list").strip().lower()
    data["view_mode"] = "grid" if mode == "grid" else "list"
    data["window_width"] = _normalize_window_dim(
        data.get("window_width"), _DEFAULT_WINDOW_WIDTH, minimum=400
    )
    data["window_height"] = _normalize_window_dim(
        data.get("window_height"), _DEFAULT_WINDOW_HEIGHT, minimum=300
    )
    data["window_maximized"] = bool(data.get("window_maximized"))
    data["last_path"] = _normalize_last_path_value(data.get("last_path"))
    from .i18n import normalize_language

    data["language"] = normalize_language(data.get("language"))
    return data


def _normalize_sync_exclude(value: Any) -> str:
    """Keep exclude text as a newline-separated string (list values joined)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        lines = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(lines)
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def normalize_sync_remote_root(value: Any) -> str:
    """Allow only ``/my-files`` or a subtree under it; anything else → ``/my-files``."""
    path = str(value or "").strip()
    if not path.startswith("/"):
        path = f"/{path}" if path else "/my-files"
    while path.endswith("/") and path != "/":
        path = path[:-1]
    if path == "/my-files":
        return path
    if path.startswith("/my-files/") and len(path) > len("/my-files/"):
        return path
    return "/my-files"


# Official CLI filesystem -f values shared by upload and download (no replace/remove).
SYNC_CONFLICT_POLICIES = ("skip", "rename")

# Always-on sync direction: which half of the download/upload pass runs.
SYNC_DIRECTIONS = ("bidirectional", "upload-only", "download-only")

# Always-on poll interval (GUI due-check + optional systemd OnUnitActiveSec).
SYNC_INTERVAL_SECONDS_DEFAULT = 300
SYNC_INTERVAL_SECONDS_MIN = 60
SYNC_INTERVAL_SECONDS_MAX = 86400

# Optional per-pass watchdog (0 = off). When set, clamps to [60, 86400].
SYNC_PASS_TIMEOUT_SECONDS_DEFAULT = 0
SYNC_PASS_TIMEOUT_SECONDS_MIN = 60
SYNC_PASS_TIMEOUT_SECONDS_MAX = 86400
SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED = 3600


def normalize_sync_conflict_policy(value: Any) -> str:
    """Always-on conflict policy: ``skip`` (default) or ``rename``.

    Maps to official ``proton-drive filesystem upload|download`` ``-f`` /
    ``--file-conflict-strategy``. Unknown values fall back to ``skip``.
    """
    text = str(value or "").strip().lower().replace("_", "-")
    if text == "rename":
        return "rename"
    return "skip"


def normalize_sync_direction(value: Any) -> str:
    """Always-on sync direction: ``bidirectional`` (default), ``upload-only``, or ``download-only``.

    Bidirectional is the desktop default (download then upload). Upload-only is
    one-way local → Drive (TrueNAS-style). Download-only is one-way Drive → local.
    Unknown values fall back to ``bidirectional``.
    """
    text = str(value or "").strip().lower().replace("_", "-")
    if text in ("upload-only", "upload"):
        return "upload-only"
    if text in ("download-only", "download"):
        return "download-only"
    if text in ("bidirectional", "both", "two-way"):
        return "bidirectional"
    return "bidirectional"


def normalize_sync_interval_seconds(value: Any) -> int:
    """Clamp always-on sync interval to ``[60, 86400]``; invalid → 300.

    Used by Settings, GUI ``due_for_pass``, and systemd timer generation.
    """
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return SYNC_INTERVAL_SECONDS_DEFAULT
    if seconds < SYNC_INTERVAL_SECONDS_MIN:
        return SYNC_INTERVAL_SECONDS_MIN
    if seconds > SYNC_INTERVAL_SECONDS_MAX:
        return SYNC_INTERVAL_SECONDS_MAX
    return seconds


def normalize_sync_pass_timeout_seconds(value: Any) -> int:
    """Optional per-pass watchdog seconds: ``0`` (default, off) or ``[60, 86400]``.

    Invalid / negative values become ``0`` (disabled). Positive values below the
    minimum clamp to 60. Used by Settings and the always-on ``run_once`` worker.
    """
    if value is None or value is False or value == "":
        return SYNC_PASS_TIMEOUT_SECONDS_DEFAULT
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return SYNC_PASS_TIMEOUT_SECONDS_DEFAULT
    if seconds <= 0:
        return 0
    if seconds < SYNC_PASS_TIMEOUT_SECONDS_MIN:
        return SYNC_PASS_TIMEOUT_SECONDS_MIN
    if seconds > SYNC_PASS_TIMEOUT_SECONDS_MAX:
        return SYNC_PASS_TIMEOUT_SECONDS_MAX
    return seconds


def _normalize_window_dim(value: Any, default: int, *, minimum: int) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return default
    if size <= 0:
        return default
    return max(minimum, min(size, 10000))


def _normalize_last_path_value(value: Any) -> str:
    """Keep a Drive path string; unknown shapes fall back to My files root."""
    path = str(value or "").strip()
    if not path.startswith("/"):
        return "/my-files"
    while path.endswith("/") and path != "/":
        path = path[:-1]
    if path in ("/my-files", "/photos", "/shared-with-me", "/trash"):
        return path
    for prefix in ("/my-files/", "/photos/", "/shared-with-me/", "/trash/", "/albums/"):
        if path.startswith(prefix) and len(path) > len(prefix):
            return path
    if path == "/albums":
        return "/photos"
    return "/my-files"


def save(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(_DEFAULTS)
    payload.update(data)
    explicit_pairs = isinstance(data.get("sync_pairs"), list) and bool(data.get("sync_pairs"))
    if explicit_pairs:
        pairs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in data["sync_pairs"]:
            pair = normalize_sync_pair(item)
            if pair is None:
                continue
            if pair["id"] in seen:
                pair["id"] = new_sync_pair_id()
            seen.add(pair["id"])
            pairs.append(pair)
        if not pairs:
            pairs = ensure_sync_pairs(payload)
            pairs = apply_legacy_sync_fields_to_primary(payload, pairs)
    else:
        pairs = ensure_sync_pairs(payload)
        pairs = apply_legacy_sync_fields_to_primary(payload, pairs)
    payload["sync_pairs"] = pairs
    mirror_primary_pair_to_legacy(payload, pairs)
    payload["sync_enabled"] = bool(payload.get("sync_enabled"))
    payload["sync_paused"] = bool(payload.get("sync_paused"))
    payload["setup_completed"] = bool(payload.get("setup_completed"))
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


def sync_delta_path() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return SYNC_DELTA_PATH


def sync_path_request_path() -> Path:
    """Stamp file: local path-trigger asked for a sync pass soon."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return SYNC_PATH_REQUEST_PATH


def empty_sync_delta(
    *,
    folder: str = "",
    remote_root: str = "/my-files",
    direction: str = "bidirectional",
) -> dict[str, Any]:
    """Blank local-delta state for one always-on sync pair."""
    return {
        "version": _SYNC_DELTA_VERSION,
        "folder": str(folder or ""),
        "remote_root": str(remote_root or "/my-files"),
        "direction": str(direction or "bidirectional"),
        "items": {},
    }


def parse_sync_delta(raw: Any) -> dict[str, Any]:
    """Normalize one pair's sync-delta (per top-level child mtime/size fingerprints)."""
    data = empty_sync_delta()
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
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version != _SYNC_DELTA_VERSION:
        return data
    data["folder"] = str(payload.get("folder") or "")
    data["remote_root"] = str(payload.get("remote_root") or "/my-files")
    data["direction"] = str(payload.get("direction") or "bidirectional")
    items_raw = payload.get("items")
    items: dict[str, Any] = {}
    if isinstance(items_raw, dict):
        for name, entry in items_raw.items():
            key = str(name or "").strip()
            if not key or not isinstance(entry, dict):
                continue
            items[key] = dict(entry)
    data["items"] = items
    return data


def empty_sync_delta_store() -> dict[str, Any]:
    return {"version": _SYNC_DELTA_STORE_VERSION, "pairs": {}}


def _parse_delta_store(raw: Any) -> dict[str, Any]:
    """Load multi-pair delta store; migrate legacy single-pair (v1) files."""
    store = empty_sync_delta_store()
    payload: dict[str, Any]
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return store
        payload = loaded if isinstance(loaded, dict) else {}
    elif isinstance(raw, dict):
        payload = raw
    else:
        return store
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version == _SYNC_DELTA_STORE_VERSION and isinstance(payload.get("pairs"), dict):
        pairs: dict[str, Any] = {}
        for key, entry in payload["pairs"].items():
            pair_id = str(key or "").strip()
            if not pair_id or not isinstance(entry, dict):
                continue
            pairs[pair_id] = parse_sync_delta(entry)
        store["pairs"] = pairs
        return store
    # Legacy v1: entire file is one pair's delta (folder/items at top level).
    if version == _SYNC_DELTA_VERSION or "items" in payload or "folder" in payload:
        legacy = parse_sync_delta(payload)
        store["pairs"] = {"default": legacy}
    return store


def load_sync_delta_store() -> dict[str, Any]:
    if not SYNC_DELTA_PATH.is_file():
        return empty_sync_delta_store()
    try:
        raw = SYNC_DELTA_PATH.read_text(encoding="utf-8")
    except OSError:
        return empty_sync_delta_store()
    return _parse_delta_store(raw)


def save_sync_delta_store(store: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    pairs_raw = store.get("pairs") if isinstance(store, dict) else {}
    pairs: dict[str, Any] = {}
    if isinstance(pairs_raw, dict):
        for key, entry in pairs_raw.items():
            pair_id = str(key or "").strip()
            if not pair_id:
                continue
            pairs[pair_id] = parse_sync_delta(entry)
    payload = {"version": _SYNC_DELTA_STORE_VERSION, "pairs": pairs}
    SYNC_DELTA_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _default_delta_pair_id(cfg: dict[str, Any] | None = None) -> str:
    data = cfg if cfg is not None else load()
    pairs = ensure_sync_pairs(data)
    if pairs:
        return str(pairs[0].get("id") or "default")
    return "default"


def load_sync_delta(pair_id: str | None = None) -> dict[str, Any]:
    """Load delta for one pair (defaults to the primary / first pair)."""
    store = load_sync_delta_store()
    pairs = store.get("pairs") if isinstance(store.get("pairs"), dict) else {}
    key = str(pair_id or "").strip() or _default_delta_pair_id()
    entry = pairs.get(key)
    if isinstance(entry, dict):
        return parse_sync_delta(entry)
    # Fall back to legacy "default" slot when primary id changed after migration.
    if key != "default" and isinstance(pairs.get("default"), dict):
        return parse_sync_delta(pairs["default"])
    return empty_sync_delta()


def save_sync_delta(data: dict[str, Any], pair_id: str | None = None) -> None:
    """Save one pair's delta into the multi-pair store."""
    store = load_sync_delta_store()
    pairs = store.get("pairs") if isinstance(store.get("pairs"), dict) else {}
    if not isinstance(pairs, dict):
        pairs = {}
    key = str(pair_id or "").strip() or _default_delta_pair_id()
    pairs[key] = parse_sync_delta(data)
    store["pairs"] = pairs
    save_sync_delta_store(store)


def parse_activity_history_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        pull = int(raw.get("pull") or 0)
        push = int(raw.get("push") or 0)
        skipped_pull = int(raw.get("skipped_pull") or 0)
        skipped_push = int(raw.get("skipped_push") or 0)
        pair_count = int(raw.get("pair_count") or 0)
    except (TypeError, ValueError):
        return None
    return {
        "finished": str(raw.get("finished") or ""),
        "pull": max(0, pull),
        "push": max(0, push),
        "skipped_pull": max(0, skipped_pull),
        "skipped_push": max(0, skipped_push),
        "errors": str(raw.get("errors") or "")[:2000],
        "timeout": bool(raw.get("timeout")),
        "pair_count": max(0, pair_count),
        "message": str(raw.get("message") or "")[:500],
    }


def parse_sync_status(raw: Any) -> dict[str, Any]:
    """Normalize worker status JSON (XDG sync-status.json) into known fields."""
    data = {key: (list(value) if key == "history" else value) for key, value in _SYNC_STATUS_DEFAULTS.items()}
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
    int_keys = {
        "last_pull",
        "last_push",
        "last_skipped_pull",
        "last_skipped_push",
        "last_pair_count",
        "pid",
    }
    bool_keys = {"last_timeout"}
    for key in _SYNC_STATUS_DEFAULTS:
        if key == "history":
            continue
        if key not in payload or payload[key] is None:
            continue
        if key in int_keys:
            try:
                data[key] = int(payload[key])
            except (TypeError, ValueError):
                data[key] = 0
        elif key in bool_keys:
            data[key] = bool(payload[key])
        else:
            data[key] = str(payload[key])
    history_raw = payload.get("history")
    history: list[dict[str, Any]] = []
    if isinstance(history_raw, list):
        for item in history_raw:
            entry = parse_activity_history_entry(item)
            if entry is not None:
                history.append(entry)
    data["history"] = history[-SYNC_ACTIVITY_HISTORY_MAX:]
    if not str(data.get("last_success") or "").strip():
        if not str(data.get("last_error") or "").strip() and str(data.get("last_finished") or "").strip():
            data["last_success"] = str(data["last_finished"])
    return data


def append_sync_activity_history(
    status: dict[str, Any],
    *,
    finished: str,
    pull: int,
    push: int,
    skipped_pull: int = 0,
    skipped_push: int = 0,
    errors: str = "",
    timeout: bool = False,
    pair_count: int = 0,
    message: str = "",
) -> dict[str, Any]:
    """Append one bounded Activity history entry onto a status payload."""
    payload = parse_sync_status(status)
    entry = parse_activity_history_entry(
        {
            "finished": finished,
            "pull": pull,
            "push": push,
            "skipped_pull": skipped_pull,
            "skipped_push": skipped_push,
            "errors": errors,
            "timeout": timeout,
            "pair_count": pair_count,
            "message": message,
        }
    )
    history = list(payload.get("history") or [])
    if entry is not None:
        history.append(entry)
    payload["history"] = history[-SYNC_ACTIVITY_HISTORY_MAX:]
    return payload


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
