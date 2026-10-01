#!/usr/bin/env bash
# Build a reproducible-ish source tarball and SHA-256 checksums for GitHub Releases.
# Usage: scripts/build-source-tarball.sh [VERSION]
# VERSION defaults to the git tag (v* → strip v) or packaging/arch/PKGBUILD pkgver.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${DIST_DIR:-$ROOT/dist}"
NAME_PREFIX="proton-drive-desktop"

resolve_version() {
  if [ -n "${1:-}" ]; then
    echo "${1#v}"
    return
  fi
  if [ -n "${GITHUB_REF_NAME:-}" ] && [[ "${GITHUB_REF_NAME}" == v* ]]; then
    echo "${GITHUB_REF_NAME#v}"
    return
  fi
  if git -C "$ROOT" describe --tags --exact-match HEAD >/dev/null 2>&1; then
    local tag
    tag="$(git -C "$ROOT" describe --tags --exact-match HEAD)"
    echo "${tag#v}"
    return
  fi
  sed -n 's/^pkgver=//p' "$ROOT/packaging/arch/PKGBUILD" | head -n1
}

VERSION="$(resolve_version "${1:-}")"
[ -n "$VERSION" ] || { echo "Could not resolve version" >&2; exit 1; }

ARCHIVE_BASE="${NAME_PREFIX}-${VERSION}"
TARBALL="${ARCHIVE_BASE}.tar.gz"

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$TARBALL"

if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # Prefer git archive so the tarball matches a commit (excludes untracked build junk).
  git -C "$ROOT" archive --format=tar.gz --prefix="${ARCHIVE_BASE}/" -o "$OUT_DIR/$TARBALL" HEAD
else
  # Fallback for a detached export without .git
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  mkdir -p "$TMP/$ARCHIVE_BASE"
  # shellcheck disable=SC2164
  (
    cd "$ROOT"
    tar --exclude='.git' --exclude='dist' --exclude='build' --exclude='.venv' \
      --exclude='__pycache__' --exclude='*.pyc' --exclude='locale' \
      -cf - . | tar -C "$TMP/$ARCHIVE_BASE" -xf -
  )
  tar -C "$TMP" -czf "$OUT_DIR/$TARBALL" "$ARCHIVE_BASE"
fi

(
  cd "$OUT_DIR"
  # Rewrite SHA256SUMS for the source tarball; AppImage build appends when present.
  if [ -f SHA256SUMS ]; then
    grep -v " ${TARBALL}\$" SHA256SUMS > SHA256SUMS.tmp 2>/dev/null || true
    mv SHA256SUMS.tmp SHA256SUMS
  else
    : > SHA256SUMS
  fi
  sha256sum "$TARBALL" >> SHA256SUMS
  sort -k2 SHA256SUMS -o SHA256SUMS
)

echo "Wrote $OUT_DIR/$TARBALL"
echo "Wrote $OUT_DIR/SHA256SUMS"
sha256sum "$OUT_DIR/$TARBALL"
