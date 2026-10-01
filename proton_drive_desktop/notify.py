"""Desktop notifications via notify-send for always-on worker / auth events."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR
from .i18n import _
from .paths import APP_ICON_NAME, icon_png

# Coalesce repeats of the same failure across worker --once passes (default interval 300s).
DEBOUNCE_SECONDS = 900

_NOTIFY_STATE_NAME = "notify-state.json"


def notify_state_path() -> Path:
    return CONFIG_DIR / _NOTIFY_STATE_NAME


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_state() -> dict[str, Any]:
    path = notify_state_path()
    if not path.is_file():
        return {"key": "", "at": ""}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"key": "", "at": ""}
    if not isinstance(raw, dict):
        return {"key": "", "at": ""}
    return {"key": str(raw.get("key") or ""), "at": str(raw.get("at") or "")}


def _save_state(key: str, at: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    notify_state_path().write_text(
        json.dumps({"key": key, "at": at}, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_notify_state() -> None:
    """Drop debounce state after a successful sync pass."""
    path = notify_state_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def notification_fingerprint(kind: str, detail: str) -> str:
    line = str(detail or "").strip().splitlines()[0].strip() if detail else ""
    if len(line) > 200:
        line = line[:200]
    return f"{kind}:{line}"


def _age_seconds(iso: str) -> float | None:
    text = str(iso or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds()


def should_notify(kind: str, detail: str, *, debounce_seconds: int = DEBOUNCE_SECONDS) -> bool:
    """True unless the same kind+detail was already sent within the debounce window."""
    key = notification_fingerprint(kind, detail)
    state = _load_state()
    if state["key"] != key:
        return True
    age = _age_seconds(state["at"])
    if age is None:
        return True
    return age >= debounce_seconds


def mark_notified(kind: str, detail: str) -> None:
    _save_state(notification_fingerprint(kind, detail), utc_now())


def is_auth_failure(text: str) -> bool:
    lower = str(text or "").lower()
    return "need to login" in lower or "not logged in" in lower


def notify_send(
    summary: str,
    body: str = "",
    *,
    urgency: str = "normal",
    icon: str | None = None,
) -> bool:
    """Fire a desktop notification. Returns False if notify-send is missing or fails."""
    binary = shutil.which("notify-send")
    if not binary:
        return False
    summary_text = str(summary or "").strip() or "Proton Drive Desktop"
    body_text = str(body or "").strip()
    icon_path = icon
    if not icon_path:
        png = icon_png(48)
        icon_path = str(png) if png.is_file() else APP_ICON_NAME
    cmd = [
        binary,
        "--app-name=Proton Drive Desktop",
        f"--urgency={urgency}",
        f"--icon={icon_path}",
        "--category=transfer.error",
        summary_text,
    ]
    if body_text:
        cmd.append(body_text)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def notify_worker_failure(detail: str, *, auth_expired: bool | None = None) -> bool:
    """Notify on always-on worker failure or auth expiry; coalesce identical repeats."""
    text = str(detail or "").strip()
    expired = bool(auth_expired) if auth_expired is not None else is_auth_failure(text)
    if expired:
        kind = "auth"
        summary = _("Proton Drive session expired")
        body = _("Sign in again so the always-on folder can sync.")
        urgency = "critical"
    else:
        kind = "worker"
        summary = _("Always-on folder failed")
        line = text.splitlines()[0].strip() if text else ""
        if len(line) > 160:
            line = f"{line[:157]}..."
        body = line or _("Check Settings → Last error for details.")
        urgency = "normal"
    if not should_notify(kind, body if expired else text):
        return False
    if not notify_send(summary, body, urgency=urgency):
        return False
    mark_notified(kind, body if expired else text)
    return True
