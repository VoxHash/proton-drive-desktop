#!/usr/bin/env bash
# Build an AppImage that bundles this GTK GUI only.
# Runtime still requires a system `proton-drive` on PATH (never vendored here).
#
# Output: dist/ProtonDriveDesktop-<arch>.AppImage
#
# Requirements: bash, make, python3, curl, gettext (msgfmt).
# Downloads appimagetool into dist/.tools/ when missing.
# Host at runtime still needs python3 + PyGObject + GTK4 + libadwaita
# (this recipe does not freeze GI/GTK with PyInstaller).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${APPIMAGE_BUILD_DIR:-$ROOT/dist/appimage-build}"
APPDIR="$BUILD_DIR/AppDir"
TOOLS_DIR="${APPIMAGE_TOOLS_DIR:-$ROOT/dist/.tools}"
OUT_DIR="${DIST_DIR:-$ROOT/dist}"
APP_ID="io.github.voxhash.ProtonDriveDesktop"
ARCH="$(uname -m)"

say() { echo "==> $*"; }
die() { echo "error: $*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v make >/dev/null 2>&1 || die "make is required"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v msgfmt >/dev/null 2>&1 || die "gettext (msgfmt) is required"

resolve_version() {
  if [ -n "${1:-}" ]; then
    echo "${1#v}"
    return
  fi
  if [ -n "${GITHUB_REF_NAME:-}" ] && [[ "${GITHUB_REF_NAME}" == v* ]]; then
    echo "${GITHUB_REF_NAME#v}"
    return
  fi
  sed -n 's/^pkgver=//p' "$ROOT/packaging/arch/PKGBUILD" | head -n1
}

VERSION="$(resolve_version "${1:-}")"
[ -n "$VERSION" ] || die "Could not resolve version"

OUT_NAME="ProtonDriveDesktop-${VERSION}-${ARCH}.AppImage"
OUT_PATH="$OUT_DIR/$OUT_NAME"

say "Preparing AppDir (GUI only; no Proton CLI)"
rm -rf "$APPDIR"
mkdir -p "$APPDIR" "$OUT_DIR" "$TOOLS_DIR"

make -C "$ROOT" DESTDIR="$APPDIR" PREFIX=/usr install

# AppImage metadata at AppDir root
install -Dm755 "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
install -Dm644 "$APPDIR/usr/share/applications/${APP_ID}.desktop" "$APPDIR/${APP_ID}.desktop"
# Exec must be AppRun-compatible (binary name on PATH inside the image)
sed -i 's|^Exec=.*|Exec=proton-drive-desktop|' "$APPDIR/${APP_ID}.desktop"
# appimagetool looks for *.appdata.xml; we already ship AppStream as *.metainfo.xml
if [ -f "$APPDIR/usr/share/metainfo/${APP_ID}.metainfo.xml" ]; then
  install -Dm644 "$APPDIR/usr/share/metainfo/${APP_ID}.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/${APP_ID}.appdata.xml"
fi
if [ -f "$APPDIR/usr/share/icons/hicolor/256x256/apps/${APP_ID}.png" ]; then
  cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/${APP_ID}.png" "$APPDIR/${APP_ID}.png"
elif [ -f "$APPDIR/usr/share/icons/hicolor/128x128/apps/${APP_ID}.png" ]; then
  cp "$APPDIR/usr/share/icons/hicolor/128x128/apps/${APP_ID}.png" "$APPDIR/${APP_ID}.png"
fi

# Hard rule: never ship Proton's prebuilt CLI inside the AppImage
if find "$APPDIR" -type f \( -name 'proton-drive' -o -name 'proton-drive.exe' \) 2>/dev/null | grep -q .; then
  die "Refusing to package: found a proton-drive binary inside AppDir (must not vendor Proton CLI)"
fi

APPIMAGETOOL="$TOOLS_DIR/appimagetool-${ARCH}.AppImage"
if [ ! -x "$APPIMAGETOOL" ]; then
  say "Downloading appimagetool for ${ARCH}"
  case "$ARCH" in
    x86_64|amd64) TOOL_ARCH=x86_64 ;;
    aarch64|arm64) TOOL_ARCH=aarch64 ;;
    *) die "Unsupported architecture for appimagetool: $ARCH" ;;
  esac
  curl -fSL -o "$APPIMAGETOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${TOOL_ARCH}.AppImage"
  chmod +x "$APPIMAGETOOL"
fi

say "Packing $OUT_NAME"
# --appimage-extract-and-run avoids needing FUSE for appimagetool itself
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$OUT_PATH"

(
  cd "$OUT_DIR"
  if [ -f SHA256SUMS ]; then
    grep -v " ${OUT_NAME}\$" SHA256SUMS > SHA256SUMS.tmp 2>/dev/null || true
    mv SHA256SUMS.tmp SHA256SUMS
  else
    : > SHA256SUMS
  fi
  sha256sum "$OUT_NAME" >> SHA256SUMS
  sort -k2 SHA256SUMS -o SHA256SUMS
)

say "Done: $OUT_PATH"
echo "This AppImage bundles the GTK GUI only. Install official proton-drive on PATH separately"
echo "(see https://proton.me/download/drive/cli/index.html). Host needs python3, PyGObject, GTK4, libadwaita."
