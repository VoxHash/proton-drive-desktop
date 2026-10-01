#!/usr/bin/env bash
# One-shot installer for Proton Drive Desktop (GTK GUI).
#
# 1. Installs system GTK / PyGObject deps (apt / dnf / pacman).
# 2. User-installs the desktop launcher via `make user-install`.
# 3. Optionally downloads the official proton-drive CLI from Proton's
#    published index, only after verifying the SHA-512 checksum
#    (same URL and parsing model as proton_drive_desktop/cli_verify.py).
#
# Usage:
#   ./install.sh              # deps + GUI; download CLI if missing
#   ./install.sh --skip-cli   # deps + GUI only
#   ./install.sh --with-cli   # deps + GUI; download CLI even if present (re-verify)
#   ./install.sh --yes        # non-interactive (assume yes for sudo package installs)
#
# Never silently installs a CLI that fails checksum verification.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_BIN="${HOME}/.local/bin"
CLI_INDEX_URL="https://proton.me/download/drive/cli/index.html"
SKIP_CLI=0
FORCE_CLI=0
ASSUME_YES=0

c_bold=$'\033[1m'; c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_red=$'\033[31m'; c_reset=$'\033[0m'
say() { echo "${c_bold}==>${c_reset} $*"; }
ok() { echo "${c_green}OK${c_reset} $*"; }
warn() { echo "${c_yellow}!${c_reset} $*"; }
die() { echo "${c_red}error: $*${c_reset}" >&2; exit 1; }

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-cli) SKIP_CLI=1 ;;
    --with-cli) FORCE_CLI=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) usage ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

# -- 1. system packages -------------------------------------------------------

install_system_deps() {
  say "Installing GTK4 / libadwaita / PyGObject system packages"

  if command -v pacman >/dev/null 2>&1; then
    local pkgs=(python python-gobject gtk4 libadwaita gdk-pixbuf2 libsecret gettext hicolor-icon-theme)
    if [ "$ASSUME_YES" -eq 1 ]; then
      sudo pacman -S --needed --noconfirm "${pkgs[@]}"
    else
      sudo pacman -S --needed "${pkgs[@]}"
    fi
  elif command -v apt-get >/dev/null 2>&1; then
    local pkgs=(
      python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
      libgtk-4-1 libadwaita-1-0 libgdk-pixbuf-2.0-0
      libsecret-1-0 gettext curl
    )
    sudo apt-get update
    if [ "$ASSUME_YES" -eq 1 ]; then
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${pkgs[@]}"
    else
      sudo apt-get install --no-install-recommends "${pkgs[@]}"
    fi
  elif command -v dnf >/dev/null 2>&1; then
    local pkgs=(python3 python3-gobject gtk4 libadwaita gdk-pixbuf2 libsecret gettext curl)
    if [ "$ASSUME_YES" -eq 1 ]; then
      sudo dnf install -y "${pkgs[@]}"
    else
      sudo dnf install "${pkgs[@]}"
    fi
  elif command -v zypper >/dev/null 2>&1; then
    local pkgs=(python3 python3-gobject gtk4 libadwaita-1-0 gdk-pixbuf-2.0 libsecret-1-0 gettext-tools curl)
    if [ "$ASSUME_YES" -eq 1 ]; then
      sudo zypper --non-interactive install "${pkgs[@]}"
    else
      sudo zypper install "${pkgs[@]}"
    fi
  else
    warn "Unrecognized package manager — install python3, PyGObject, GTK4, libadwaita, libsecret, gettext yourself."
  fi
  ok "System dependency step finished"
}

# -- 2. GUI user-install ------------------------------------------------------

install_gui() {
  say "Installing Proton Drive Desktop for the current user (make user-install)"
  command -v make >/dev/null 2>&1 || die "make is required"
  command -v msgfmt >/dev/null 2>&1 || die "gettext (msgfmt) is required"
  make -C "$PROJECT_DIR" user-install
  ok "Desktop launcher and icons installed under ${HOME}/.local"
}

# -- 3. optional official CLI (SHA-512 verified) ------------------------------

detect_platform_key() {
  # Returns Proton index key, e.g. linux/x64 or linux/x64-musl
  local arch suffix=""
  arch="$(uname -m)"
  [ "$(uname -s)" = "Linux" ] || die "install.sh supports Linux only"

  if command -v apk >/dev/null 2>&1 || { [ -f /etc/os-release ] && grep -qi '^ID=alpine' /etc/os-release; }; then
    suffix="-musl"
  fi

  case "$arch" in
    x86_64|amd64) echo "linux/x64${suffix}" ;;
    aarch64|arm64) echo "linux/arm64${suffix}" ;;
    *) die "Unsupported CPU architecture: $arch" ;;
  esac
}

# Parse Proton's HTML index with the same regex model as cli_verify.py.
# Prints: URL<TAB>SHA512 for the requested platform key ($1).
lookup_cli_release() {
  local platform="$1"
  PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$platform" "$CLI_INDEX_URL" <<'PY'
import re
import sys
import urllib.request

platform = sys.argv[1]
index_url = sys.argv[2]
href_re = re.compile(r'href="(https://[^"]+)"', re.IGNORECASE)

req = urllib.request.Request(
    index_url,
    headers={
        "User-Agent": "proton-drive-desktop/install.sh",
        "Accept": "text/html,application/xhtml+xml",
    },
    method="GET",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    html = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")

# Walk table rows: platform cell, then URL cell, then checksum
chunks = re.split(r"<tr\b", html, flags=re.IGNORECASE)
for chunk in chunks:
    cells = re.findall(r"<td\b[^>]*>(.*?)</td>", chunk, flags=re.IGNORECASE | re.DOTALL)
    if len(cells) < 3:
        continue
    plat = re.sub(r"<[^>]+>", "", cells[0]).strip()
    if plat != platform:
        continue
    href = href_re.search(cells[1])
    code = re.search(r"<code>\s*([0-9a-fA-F]{128})\s*</code>", cells[2], re.IGNORECASE)
    if not href or not code:
        # fallback: any https in cell + any 128-hex
        urls = re.findall(r"https://[^\s<>\"']+", cells[1])
        digests = re.findall(r"\b([0-9a-fA-F]{128})\b", cells[2])
        if not urls or not digests:
            continue
        print(f"{urls[0]}\t{digests[0].lower()}")
        raise SystemExit(0)
    print(f"{href.group(1)}\t{code.group(1).lower()}")
    raise SystemExit(0)

# Also accept markdown-style fixtures (tests / mirrors)
md = re.compile(
    r"\|\s*(linux/[^\s|]+)\s*\|\s*(https?://[^\s|]+)\s*\|\s*`?([0-9a-fA-F]{128})`?\s*\|",
    re.IGNORECASE,
)
for match in md.finditer(html):
    if match.group(1).strip() == platform:
        print(f"{match.group(2).strip()}\t{match.group(3).strip().lower()}")
        raise SystemExit(0)

print(f"error: platform {platform!r} not found in {index_url}", file=sys.stderr)
raise SystemExit(1)
PY
}

download_and_verify_cli() {
  local platform="$1"
  local row url expected actual tmpfile
  say "Resolving proton-drive ($platform) from Proton's published index"
  row="$(lookup_cli_release "$platform")" || die "Could not parse Proton CLI index at $CLI_INDEX_URL"
  url="${row%%$'\t'*}"
  expected="${row#*$'\t'}"
  [[ "$expected" =~ ^[0-9a-f]{128}$ ]] || die "Invalid SHA-512 from index: $expected"

  tmpfile="$(mktemp)"
  say "Downloading $url"
  if command -v curl >/dev/null 2>&1; then
    curl -fSL --progress-bar -o "$tmpfile" "$url" || { rm -f "$tmpfile"; die "Download failed: $url"; }
  else
    PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$url" "$tmpfile" <<'PY' || { rm -f "$tmpfile"; die "Download failed: $url"; }
import sys, urllib.request
url, dest = sys.argv[1], sys.argv[2]
urllib.request.urlretrieve(url, dest)
PY
  fi

  say "Verifying SHA-512 against Proton's published checksum"
  actual="$(sha512sum "$tmpfile" | awk '{print $1}')"
  if [ "$actual" != "$expected" ]; then
    rm -f "$tmpfile"
    die "SHA-512 mismatch for proton-drive (refusing to install). expected=${expected:0:16}… actual=${actual:0:16}…"
  fi
  ok "SHA-512 verified for $platform"

  mkdir -p "$LOCAL_BIN"
  chmod 755 "$tmpfile"
  mv "$tmpfile" "$LOCAL_BIN/proton-drive"
  ok "Installed $LOCAL_BIN/proton-drive"

  # Older x64 CPUs may SIGILL on the default build — fall back to baseline.
  if [ "$platform" = "linux/x64" ]; then
    set +e
    "$LOCAL_BIN/proton-drive" --help >/dev/null 2>&1
    local code=$?
    set -e
    if [ "$code" -eq 132 ] || [ "$code" -eq 133 ]; then
      warn "Default linux/x64 build crashed (Illegal instruction) — trying linux/x64-baseline"
      download_and_verify_cli "linux/x64-baseline"
    fi
  fi
}

install_cli() {
  if [ "$SKIP_CLI" -eq 1 ]; then
    say "Skipping official CLI download (--skip-cli)"
    return
  fi

  if [ "$FORCE_CLI" -eq 0 ] && command -v proton-drive >/dev/null 2>&1; then
    ok "proton-drive already on PATH ($(command -v proton-drive)) — skipping download"
    say "Optional: re-run with --with-cli to re-download and verify against Proton's SHA-512"
    return
  fi
  if [ "$FORCE_CLI" -eq 0 ] && [ -x "$LOCAL_BIN/proton-drive" ]; then
    ok "proton-drive already at $LOCAL_BIN/proton-drive — skipping download"
    return
  fi

  local plat
  plat="$(detect_platform_key)"
  download_and_verify_cli "$plat"

  case ":$PATH:" in
    *":$LOCAL_BIN:"*) ;;
    *)
      warn "$LOCAL_BIN is not on PATH. Add to your shell rc:"
      warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
      ;;
  esac
}

# -- main ---------------------------------------------------------------------

main() {
  say "Proton Drive Desktop — one-shot install"
  install_system_deps
  install_gui
  install_cli

  echo
  ok "Install finished"
  echo
  say "Next:"
  if command -v proton-drive >/dev/null 2>&1; then
    echo "  proton-drive auth login"
  elif [ -x "$LOCAL_BIN/proton-drive" ]; then
    echo "  $LOCAL_BIN/proton-drive auth login"
  else
    echo "  Install the official CLI from $CLI_INDEX_URL (or re-run without --skip-cli)"
  fi
  echo "  proton-drive-desktop"
  echo
  echo "This installer never vendors Proton binaries inside the GUI package."
  echo "CLI downloads are verified against Proton's published SHA-512 at:"
  echo "  $CLI_INDEX_URL"
}

main "$@"
