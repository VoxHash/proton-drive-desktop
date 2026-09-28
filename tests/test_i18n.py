#!/usr/bin/env python3
"""GNU gettext wiring: English catalog and persisted language setting."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_linux import config  # noqa: E402
from proton_drive_linux.i18n import (  # noqa: E402
    LANGUAGE_ENGLISH,
    LANGUAGE_SYSTEM,
    _,
    install,
    language_choices,
    normalize_language,
)


def test_gettext_returns_english() -> None:
    previous = os.environ.get("LANGUAGE")
    install(LANGUAGE_ENGLISH)
    try:
        assert _("Settings") == "Settings"
        assert _("My files") == "My files"
        assert _("Language") == "Language"
        assert _("System default") == "System default"
        assert _("English") == "English"
        assert _("Always-on folder") == "Always-on folder"
        assert _("Delete permanently") == "Delete permanently"
    finally:
        if previous is None:
            os.environ.pop("LANGUAGE", None)
        else:
            os.environ["LANGUAGE"] = previous


def test_language_setting_persists(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-linux-i18n-config")
    folder.mkdir(parents=True, exist_ok=True)
    original_dir, original_path = config.CONFIG_DIR, config.CONFIG_PATH
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    try:
        config.save(
            {
                "theme": "dark",
                "language": "en",
                "download_folder": str(folder),
                "cli_path": "",
                "autostart": False,
                "sync_folder": str(folder),
                "sync_enabled": False,
            }
        )
        loaded = config.load()
        assert loaded["language"] == LANGUAGE_ENGLISH
        config.save({**loaded, "language": "system"})
        assert config.load()["language"] == LANGUAGE_SYSTEM
        assert normalize_language("en_US") == LANGUAGE_ENGLISH
        assert normalize_language("auto") == LANGUAGE_SYSTEM
        codes = [code for code, _label in language_choices()]
        assert codes == [LANGUAGE_SYSTEM, LANGUAGE_ENGLISH]
    finally:
        config.CONFIG_DIR = original_dir
        config.CONFIG_PATH = original_path


def test_english_catalog_compiles() -> None:
    po = ROOT / "po" / "en.po"
    potfiles = ROOT / "po" / "POTFILES.in"
    makefile = ROOT / "Makefile"
    assert po.is_file(), po
    text = po.read_text(encoding="utf-8")
    assert 'msgid "Settings"' in text
    assert 'msgstr "Settings"' in text
    assert 'msgid "Language"' in text
    assert "Language: en" in text
    listed = potfiles.read_text(encoding="utf-8")
    assert "proton_drive_linux/app.py" in listed
    assert "proton_drive_linux/i18n.py" in listed
    make = makefile.read_text(encoding="utf-8")
    assert "msgfmt" in make
    assert "locale/en/LC_MESSAGES" in make
    dest = Path("/tmp/proton-drive-linux-en-test.mo")
    proc = subprocess.run(["msgfmt", "--check", "-o", str(dest), str(po)], check=True, capture_output=True, text=True)
    assert dest.is_file()
    assert proc.returncode == 0
    dest.unlink(missing_ok=True)
    print("english catalog compiles")


if __name__ == "__main__":
    test_gettext_returns_english()
    test_language_setting_persists()
    test_english_catalog_compiles()
    print("i18n checks passed")
