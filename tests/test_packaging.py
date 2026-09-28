#!/usr/bin/env python3
"""Checks that do not call Proton APIs: local GUI config and install metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_linux import config  # noqa: E402
from proton_drive_linux.paths import APP_ICON_NAME, HELP_URL, icon_png, icon_svg  # noqa: E402


def test_config_roundtrip(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-linux-config-test")
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
    assert "proton_drive_linux/app.py" in potfiles
    en_po = (ROOT / "po" / "en.po").read_text(encoding="utf-8")
    assert 'msgid "Settings"' in en_po
    assert 'msgstr "Settings"' in en_po
    for code in ("ru", "zh_CN", "ar", "it", "pt", "es", "ko", "ja"):
        po_text = (ROOT / "po" / f"{code}.po").read_text(encoding="utf-8")
        assert f"Language: {code}" in po_text
        assert 'msgid "Settings"' in po_text
    pkgbuild = (ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")
    assert "proton-drive-linux" in pkgbuild


if __name__ == "__main__":
    test_config_roundtrip()
    test_official_icon_installed()
    print("packaging checks passed")
