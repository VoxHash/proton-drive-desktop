#!/usr/bin/env python3
"""Checks that do not call Proton APIs: local GUI config and install metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import config  # noqa: E402
from proton_drive_desktop.paths import APP_ICON_NAME, HELP_URL, icon_png, icon_svg  # noqa: E402


def test_config_roundtrip(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-config-test")
    folder.mkdir(parents=True, exist_ok=True)
    original_dir, original_path = config.CONFIG_DIR, config.CONFIG_PATH
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    try:
        config.save({"theme": "light", "language": "en", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": False})
        loaded = config.load()
        assert loaded["theme"] == "light"
        assert loaded["language"] == "en"
        assert loaded["download_folder"] == str(folder)
        assert loaded["sync_folder"] == str(folder)
        assert loaded["sync_enabled"] is False
    finally:
        config.CONFIG_DIR = original_dir
        config.CONFIG_PATH = original_path


def test_official_icon_installed() -> None:
    svg = icon_svg()
    assert svg.is_file(), svg
    text = svg.read_text(encoding="utf-8")
    assert "ProtonDriveApps/android-drive" in text
    assert "6D4AFF" in text
    assert icon_png(32).is_file()
    assert icon_png(48).is_file()
    desktop = (ROOT / "data" / f"{APP_ICON_NAME}.desktop").read_text(encoding="utf-8")
    assert f"Icon={APP_ICON_NAME}" in desktop
    assert "folder-remote" not in desktop
    metainfo = (ROOT / "data" / f"{APP_ICON_NAME}.metainfo.xml").read_text(encoding="utf-8")
    assert APP_ICON_NAME in metainfo
    assert HELP_URL in metainfo
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "user-install" in makefile
    assert "msgfmt" in makefile
    assert "LOCALES := en ru zh_CN ar it pt es ko ja" in makefile
    assert "locale/$$lang/LC_MESSAGES" in makefile
    potfiles = (ROOT / "po" / "POTFILES.in").read_text(encoding="utf-8")
    assert "proton_drive_desktop/app.py" in potfiles
    en_po = (ROOT / "po" / "en.po").read_text(encoding="utf-8")
    assert 'msgid "Settings"' in en_po
    assert 'msgstr "Settings"' in en_po
    for code in ("ru", "zh_CN", "ar", "it", "pt", "es", "ko", "ja"):
        po_text = (ROOT / "po" / f"{code}.po").read_text(encoding="utf-8")
        assert f"Language: {code}" in po_text
        assert 'msgid "Settings"' in po_text
    pkgbuild = (ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")
    assert "proton-drive-desktop" in pkgbuild


def test_distribution_kit() -> None:
    """Release tarball, AppImage recipe, and install.sh are present and wired."""
    install_sh = ROOT / "install.sh"
    assert install_sh.is_file(), install_sh
    install_text = install_sh.read_text(encoding="utf-8")
    assert "CLI_INDEX_URL" in install_text
    assert "proton.me/download/drive/cli/index.html" in install_text
    assert "sha512" in install_text.lower()
    assert "--skip-cli" in install_text

    tarball_sh = ROOT / "scripts" / "build-source-tarball.sh"
    assert tarball_sh.is_file(), tarball_sh
    assert "SHA256SUMS" in tarball_sh.read_text(encoding="utf-8")

    appimage_sh = ROOT / "packaging" / "appimage" / "build-appimage.sh"
    assert appimage_sh.is_file(), appimage_sh
    appimage_text = appimage_sh.read_text(encoding="utf-8")
    assert "proton-drive" in appimage_text
    assert "Refusing to package" in appimage_text

    apprun = ROOT / "packaging" / "appimage" / "AppRun"
    assert apprun.is_file(), apprun
    assert "proton-drive-desktop" in apprun.read_text(encoding="utf-8")

    release_yml = ROOT / ".github" / "workflows" / "release.yml"
    assert release_yml.is_file(), release_yml
    release_text = release_yml.read_text(encoding="utf-8")
    assert "build-source-tarball.sh" in release_text
    assert "SHA256SUMS" in release_text
    assert 'tags:' in release_text or '"v*"' in release_text

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "\ndist:" in makefile or makefile.startswith("dist:") or "\ndist:\n" in makefile
    assert "appimage:" in makefile
    assert "build-source-tarball.sh" in makefile


if __name__ == "__main__":
    test_config_roundtrip()
    test_official_icon_installed()
    test_distribution_kit()
    print("packaging checks passed")
