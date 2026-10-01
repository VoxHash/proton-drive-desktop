"""Filesystem locations for the unofficial Proton Drive Desktop GUI."""

from __future__ import annotations

from pathlib import Path

APP_ID = "io.github.voxhash.ProtonDriveDesktop"
APP_ICON_NAME = APP_ID
HELP_URL = "https://proton.me/support/drive"
CLI_HELP_URL = "https://proton.me/support/drive-cli"
CLI_DOWNLOAD_URL = "https://proton.me/download/drive/cli/index.html"
DRIVE_WEB_URL = "https://drive.proton.me"
ACCOUNT_URL = "https://account.proton.me"
TERMS_URL = "https://proton.me/legal/terms"
PRIVACY_URL = "https://proton.me/legal/privacy"
ISSUE_URL = "https://github.com/VoxHash/proton-drive-desktop/issues"
WEBSITE_URL = "https://github.com/VoxHash/proton-drive-desktop"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def icon_theme_search_path() -> Path:
    return repo_root() / "data" / "icons"


def hicolor_dir() -> Path:
    return icon_theme_search_path() / "hicolor"


def icon_svg() -> Path:
    return hicolor_dir() / "scalable" / "apps" / f"{APP_ICON_NAME}.svg"


def icon_png(size: int) -> Path:
    return hicolor_dir() / f"{size}x{size}" / "apps" / f"{APP_ICON_NAME}.png"


def cli_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "proton-drive-cli"


def xdg_autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / f"{APP_ID}.desktop"


# Optional systemd --user units for the always-on sync worker (alongside XDG autostart).
SYNC_SYSTEMD_SERVICE = "proton-drive-desktop-sync.service"
SYNC_SYSTEMD_TIMER = "proton-drive-desktop-sync.timer"
SYNC_SYSTEMD_PATH = "proton-drive-desktop-sync.path"


def systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def sync_systemd_service_path() -> Path:
    return systemd_user_dir() / SYNC_SYSTEMD_SERVICE


def sync_systemd_timer_path() -> Path:
    return systemd_user_dir() / SYNC_SYSTEMD_TIMER


def sync_systemd_path_unit_path() -> Path:
    return systemd_user_dir() / SYNC_SYSTEMD_PATH
