#!/usr/bin/env python3
"""GNU gettext: English source plus eight complete UI catalogs."""

from __future__ import annotations

import gettext
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_linux import config  # noqa: E402
from proton_drive_linux.i18n import (  # noqa: E402
    CATALOG_CODES,
    GETTEXT_DOMAIN,
    LANGUAGE_ENGLISH,
    LANGUAGE_SYSTEM,
    _,
    apply_gtk_direction,
    install,
    is_rtl,
    language_choices,
    locale_dir,
    normalize_language,
)

EXPECTED = {
    "ru": ("Параметры", "Мои файлы", "Постоянно доступная папка"),
    "zh_CN": ("设置", "我的文件", "常开文件夹"),
    "ar": ("الإعدادات", "ملفاتي", "المجلد الدائم"),
    "it": ("Impostazioni", "I miei file", "Cartella sempre attiva"),
    "pt": ("Configurações", "Meus arquivos", "Pasta sempre ativa"),
    "es": ("Ajustes", "Mis archivos", "Carpeta siempre activa"),
    "ko": ("설정", "내 파일", "상시 폴더"),
    "ja": ("設定", "マイファイル", "常時フォルダー"),
}


def _catalog_dir(code: str) -> Path:
    localedir = locale_dir(code)
    mo = localedir / code / "LC_MESSAGES" / f"{GETTEXT_DOMAIN}.mo"
    assert mo.is_file(), mo
    return localedir


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
        config.save({**config.load(), "language": "ja"})
        assert config.load()["language"] == "ja"
        config.save({**config.load(), "language": "zh_CN"})
        assert config.load()["language"] == "zh_CN"
        config.save({**config.load(), "language": "pt_BR"})
        assert config.load()["language"] == "pt"
        assert normalize_language("en_US") == LANGUAGE_ENGLISH
        assert normalize_language("auto") == LANGUAGE_SYSTEM
        assert normalize_language("ar_SA") == "ar"
        codes = [code for code, _label in language_choices()]
        assert codes[0] == LANGUAGE_SYSTEM
        assert codes[1] == LANGUAGE_ENGLISH
        for code in CATALOG_CODES:
            if code != LANGUAGE_ENGLISH:
                assert code in codes
        labels = dict(language_choices())
        assert labels["ru"] == "Русский"
        assert labels["zh_CN"] == "简体中文"
        assert labels["ar"] == "العربية"
        assert labels["it"] == "Italiano"
        assert labels["pt"] == "Português"
        assert labels["es"] == "Español"
        assert labels["ko"] == "한국어"
        assert labels["ja"] == "日本語"
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
    assert "LOCALES := en ru zh_CN ar it pt es ko ja" in make
    dest = Path("/tmp/proton-drive-linux-en-test.mo")
    proc = subprocess.run(["msgfmt", "--check", "-o", str(dest), str(po)], check=True, capture_output=True, text=True)
    assert dest.is_file()
    assert proc.returncode == 0
    dest.unlink(missing_ok=True)
    print("english catalog compiles")


def test_each_catalog_is_not_english() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "LOCALES := en ru zh_CN ar it pt es ko ja" in makefile
    for code, (settings, my_files, always_on) in EXPECTED.items():
        po = ROOT / "po" / f"{code}.po"
        assert po.is_file(), po
        text = po.read_text(encoding="utf-8")
        assert f"Language: {code}" in text
        assert "TODO" not in text
        assert "PLACEHOLDER" not in text
        assert "lorem" not in text.lower()
        dest = Path(f"/tmp/proton-drive-linux-{code}-test.mo")
        subprocess.run(["msgfmt", "--check", "-o", str(dest), str(po)], check=True, capture_output=True, text=True)
        dest.unlink(missing_ok=True)
        install(code)
        got_settings, got_files, got_folder = _("Settings"), _("My files"), _("Always-on folder")
        print(f"{code}: Settings={got_settings!r} My files={got_files!r} Always-on folder={got_folder!r}")
        assert got_settings == settings, (code, got_settings, settings)
        assert got_files == my_files, (code, got_files, my_files)
        assert got_folder == always_on, (code, got_folder, always_on)
        assert got_settings != "Settings"
        assert got_files != "My files"
        assert got_folder != "Always-on folder"
        trans = gettext.translation(GETTEXT_DOMAIN, localedir=_catalog_dir(code), languages=[code], fallback=False)
        assert trans.gettext("Settings") == settings
        if code == "ar":
            assert "الإعدادات" in got_settings
            assert any("\u0600" <= ch <= "\u06FF" for ch in got_settings)
            assert is_rtl("ar") is True
        else:
            assert is_rtl(code) is False
    install(LANGUAGE_ENGLISH)
    print("each catalog is not English")


def test_arabic_gtk_direction() -> None:
    install("ar")
    apply_gtk_direction("ar")
    from gi.repository import Gtk

    direction = Gtk.Widget.get_default_direction()
    assert direction == Gtk.TextDirection.RTL, direction
    install("ja")
    apply_gtk_direction("ja")
    assert Gtk.Widget.get_default_direction() == Gtk.TextDirection.LTR
    print("arabic GTK direction is RTL")


if __name__ == "__main__":
    test_gettext_returns_english()
    test_language_setting_persists()
    test_english_catalog_compiles()
    test_each_catalog_is_not_english()
    test_arabic_gtk_direction()
    print("i18n checks passed")
