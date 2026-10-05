#!/usr/bin/env bash
# Uninstall Proton Drive Desktop files placed by `make user-install` / `./install.sh`
# under ~/.local (and optional session helpers under ~/.config).
#
# Usage:
#   ./scripts/uninstall.sh
#   ./scripts/uninstall.sh --purge        # also delete ~/.config/proton-drive-desktop
#   ./scripts/uninstall.sh --remove-cli   # also delete ~/.local/bin/proton-drive
#   make user-uninstall                   # same as default (no purge / no CLI)
#   ./install.sh --uninstall [--purge] [--remove-cli]
#
# Default: does NOT remove the official Proton CLI (~/.local/bin/proton-drive)
# and does NOT wipe GUI config / sync state under ~/.config/proton-drive-desktop.
set -euo pipefail

APP_ID="io.github.voxhash.ProtonDriveDesktop"
GETTEXT_DOMAIN="proton-drive-desktop"
LOCALES=(en ru zh_CN ar it pt es ko ja)
SYNC_SERVICE="proton-drive-desktop-sync.service"
SYNC_TIMER="proton-drive-desktop-sync.timer"
SYNC_PATH="proton-drive-desktop-sync.path"

PREFIX="${HOME}/.local"
BINDIR="${PREFIX}/bin"
LIBDIR="${PREFIX}/lib/proton-drive-desktop"
DATADIR="${PREFIX}/share"
CONFIG_DIR="${HOME}/.config/proton-drive-desktop"
AUTOSTART="${HOME}/.config/autostart/${APP_ID}.desktop"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
CLI_BIN="${BINDIR}/proton-drive"

PURGE=0
REMOVE_CLI=0

c_bold=$'\033[1m'; c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_red=$'\033[31m'; c_reset=$'\033[0m'
say() { echo "${c_bold}==>${c_reset} $*"; }
ok() { echo "${c_green}OK${c_reset} $*"; }
warn() { echo "${c_yellow}!${c_reset} $*"; }
die() { echo "${c_red}error: $*${c_reset}" >&2; exit 1; }

usage() {
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1 ;;
    --remove-cli) REMOVE_CLI=1 ;;
    -h|--help) usage ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

remove_file() {
  local path="$1"
  if [ -e "$path" ] || [ -L "$path" ]; then
    rm -f "$path"
    ok "Removed $path"
  fi
}

remove_dir() {
  local path="$1"
  if [ -d "$path" ]; then
    rm -rf "$path"
    ok "Removed $path"
  fi
}

disable_systemd_unit() {
  local unit="$1"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
  fi
}

say "Uninstalling Proton Drive Desktop from ${PREFIX}"

# Optional systemd --user sync units (created from Settings, not make install).
disable_systemd_unit "$SYNC_TIMER"
disable_systemd_unit "$SYNC_PATH"
remove_file "${SYSTEMD_USER_DIR}/${SYNC_TIMER}"
remove_file "${SYSTEMD_USER_DIR}/${SYNC_PATH}"
remove_file "${SYSTEMD_USER_DIR}/${SYNC_SERVICE}"
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

# XDG autostart written by Settings → Start with this session.
remove_file "$AUTOSTART"

# Files from `make user-install` / `make install PREFIX=$HOME/.local`.
remove_file "${BINDIR}/proton-drive-desktop"
remove_dir "$LIBDIR"
remove_file "${DATADIR}/applications/${APP_ID}.desktop"
remove_file "${DATADIR}/metainfo/${APP_ID}.metainfo.xml"
remove_file "${DATADIR}/icons/hicolor/scalable/apps/${APP_ID}.svg"
for size in 16 22 24 32 48 64 96 128 192 256 512; do
  remove_file "${DATADIR}/icons/hicolor/${size}x${size}/apps/${APP_ID}.png"
done
for lang in "${LOCALES[@]}"; do
  remove_file "${DATADIR}/locale/${lang}/LC_MESSAGES/${GETTEXT_DOMAIN}.mo"
done

if [ "$REMOVE_CLI" -eq 1 ]; then
  say "Removing official CLI binary (--remove-cli)"
  remove_file "$CLI_BIN"
else
  if [ -e "$CLI_BIN" ] || [ -L "$CLI_BIN" ]; then
    warn "Leaving ${CLI_BIN} in place (official Proton CLI)."
    warn "Pass --remove-cli only if this installer (or you) put it there and you want it gone."
  fi
fi

if [ "$PURGE" -eq 1 ]; then
  say "Purging GUI config (--purge)"
  remove_dir "$CONFIG_DIR"
else
  if [ -d "$CONFIG_DIR" ]; then
    warn "Leaving ${CONFIG_DIR} (settings / sync state). Pass --purge to delete it."
  fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${DATADIR}/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${DATADIR}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo
ok "Uninstall finished"
echo "Re-open or refresh your applications menu if the launcher still appears until the next session."
