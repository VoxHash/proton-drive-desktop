#!/usr/bin/env bash
# Build a .deb that packages this GTK GUI only (no Proton CLI).
#
# Output: dist/proton-drive-desktop_<version>_all.deb
#
# Requirements: bash, make, python3, gettext (msgfmt), tar, gzip, ar.
# Uses dpkg-deb when available; otherwise packs a valid .deb with ar + tar.
# Runtime still requires a system proton-drive on PATH (never vendored here).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${DEB_BUILD_DIR:-$ROOT/dist/deb-build}"
OUT_DIR="${DIST_DIR:-$ROOT/dist}"
PKG_NAME="proton-drive-desktop"
CONTROL_IN="$ROOT/packaging/debian/control.in"
COPYRIGHT_SRC="$ROOT/packaging/debian/copyright"

say() { echo "==> $*"; }
die() { echo "error: $*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v make >/dev/null 2>&1 || die "make is required"
command -v msgfmt >/dev/null 2>&1 || die "gettext (msgfmt) is required"
command -v tar >/dev/null 2>&1 || die "tar is required"
command -v gzip >/dev/null 2>&1 || die "gzip is required"
command -v ar >/dev/null 2>&1 || die "ar (binutils) is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v md5sum >/dev/null 2>&1 || die "md5sum is required"
[ -f "$CONTROL_IN" ] || die "missing $CONTROL_IN"
[ -f "$COPYRIGHT_SRC" ] || die "missing $COPYRIGHT_SRC"

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
[[ "$VERSION" =~ ^[0-9]+(\.[0-9]+)*([.~+][A-Za-z0-9.+~-]+)?$ ]] || die "Invalid Debian version: $VERSION"

OUT_NAME="${PKG_NAME}_${VERSION}_all.deb"
OUT_PATH="$OUT_DIR/$OUT_NAME"
STAGE="$BUILD_DIR/${PKG_NAME}_${VERSION}_all"

say "Preparing Debian staging tree (GUI only; no Proton CLI)"
rm -rf "$STAGE"
mkdir -p "$STAGE" "$OUT_DIR"

make -C "$ROOT" DESTDIR="$STAGE" PREFIX=/usr install

install -Dm644 "$COPYRIGHT_SRC" "$STAGE/usr/share/doc/${PKG_NAME}/copyright"
install -Dm644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/${PKG_NAME}/LICENSE"
if [ -f "$ROOT/data/icons/SOURCE" ]; then
  install -Dm644 "$ROOT/data/icons/SOURCE" "$STAGE/usr/share/doc/${PKG_NAME}/ICON-SOURCE"
fi

# Debian changelog (gzipped) for /usr/share/doc
CHANGELOG_TXT="$BUILD_DIR/changelog"
cat > "$CHANGELOG_TXT" <<EOF
${PKG_NAME} (${VERSION}) unstable; urgency=medium

  * Upstream release ${VERSION}. GUI-only package; install official
    proton-drive CLI separately (PATH). See upstream CHANGELOG.md.

 -- VoxHash <15043788+VoxHash@users.noreply.github.com>  $(date -u '+%a, %d %b %Y %H:%M:%S +0000')
EOF
gzip -9n -c "$CHANGELOG_TXT" > "$STAGE/usr/share/doc/${PKG_NAME}/changelog.Debian.gz"

# Hard rule: never ship Proton's prebuilt CLI inside the .deb
if find "$STAGE" -type f \( -name 'proton-drive' -o -name 'proton-drive.exe' \) 2>/dev/null | grep -q .; then
  die "Refusing to package: found a proton-drive binary inside staging (must not vendor Proton CLI)"
fi

# Installed-Size is in KiB (Debian Policy)
INSTALLED_SIZE="$(du -sk "$STAGE" | awk '{print $1}')"
[ -n "$INSTALLED_SIZE" ] || die "Could not compute Installed-Size"

mkdir -p "$STAGE/DEBIAN"
sed \
  -e "s|@VERSION@|${VERSION}|g" \
  -e "s|@INSTALLED_SIZE@|${INSTALLED_SIZE}|g" \
  "$CONTROL_IN" > "$STAGE/DEBIAN/control"

# md5sums for data files (exclude DEBIAN/)
(
  cd "$STAGE"
  find . -type f ! -path './DEBIAN/*' -print0 \
    | sort -z \
    | xargs -0 md5sum \
    | sed 's|  \./|  |' > DEBIAN/md5sums
)

# Basic control validation
CONTROL_TEXT="$(cat "$STAGE/DEBIAN/control")"
echo "$CONTROL_TEXT" | grep -q '^Package: proton-drive-desktop$' || die "control: missing Package"
echo "$CONTROL_TEXT" | grep -q "^Version: ${VERSION}$" || die "control: bad Version"
echo "$CONTROL_TEXT" | grep -q '^Architecture: all$' || die "control: Architecture must be all"
echo "$CONTROL_TEXT" | grep -q 'python3-gi' || die "control: missing python3-gi Depends"
echo "$CONTROL_TEXT" | grep -qi 'does not ship the proton-drive' || die "control: must document CLI not bundled"

pack_with_dpkg_deb() {
  dpkg-deb --build --root-owner-group "$STAGE" "$OUT_PATH"
}

pack_with_ar() {
  local work="$BUILD_DIR/ar-pack"
  rm -rf "$work"
  mkdir -p "$work"
  printf '2.0\n' > "$work/debian-binary"

  # control.tar.gz
  tar --owner=0 --group=0 --numeric-owner \
    -C "$STAGE/DEBIAN" -cf - . \
    | gzip -9n > "$work/control.tar.gz"

  # data.tar.gz (everything except DEBIAN/)
  tar --owner=0 --group=0 --numeric-owner \
    --exclude='./DEBIAN' \
    -C "$STAGE" -cf - . \
    | gzip -9n > "$work/data.tar.gz"

  rm -f "$OUT_PATH"
  (
    cd "$work"
    ar rD "$OUT_PATH" debian-binary control.tar.gz data.tar.gz
  )
}

say "Packing $OUT_NAME"
if command -v dpkg-deb >/dev/null 2>&1; then
  pack_with_dpkg_deb
else
  say "dpkg-deb not found; packing with ar + tar"
  pack_with_ar
fi

[ -f "$OUT_PATH" ] || die "deb was not created: $OUT_PATH"
# Sanity: .deb is an ar archive
ar t "$OUT_PATH" | grep -qx 'debian-binary' || die "invalid deb: missing debian-binary"
ar t "$OUT_PATH" | grep -E -q 'control\.tar\.(gz|xz|zst)$' || die "invalid deb: missing control.tar.*"
ar t "$OUT_PATH" | grep -E -q 'data\.tar\.(gz|xz|zst)$' || die "invalid deb: missing data.tar.*"

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
echo "This .deb packages the GTK GUI only. Install official proton-drive on PATH separately"
echo "(see https://proton.me/download/drive/cli/index.html). Uninstall with: sudo dpkg -r ${PKG_NAME}"
