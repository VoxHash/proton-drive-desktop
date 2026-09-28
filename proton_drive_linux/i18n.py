"""GNU gettext for the GTK UI. English is the source language."""

from __future__ import annotations

import gettext
import locale as locale_mod
import os
from pathlib import Path

from .config import load as load_config
from .paths import repo_root

GETTEXT_DOMAIN = "proton-drive-linux"
LANGUAGE_SYSTEM = "system"
LANGUAGE_ENGLISH = "en"
SUPPORTED_LANGUAGES = (LANGUAGE_SYSTEM, LANGUAGE_ENGLISH)

_translation = gettext.NullTranslations()


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)


def locale_dir() -> Path:
    """Directory that contains <lang>/LC_MESSAGES/<domain>.mo."""
    domain_mo = Path("en") / "LC_MESSAGES" / f"{GETTEXT_DOMAIN}.mo"
    candidates: list[Path] = [
        repo_root() / "locale",
        Path.home() / ".local" / "share" / "locale",
        Path("/usr/local/share/locale"),
        Path("/usr/share/locale"),
    ]
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if data_home:
        candidates.insert(1, Path(data_home) / "locale")
    for raw in os.environ.get("XDG_DATA_DIRS", "").split(":"):
        if raw.strip():
            candidates.append(Path(raw.strip()) / "locale")
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
        if (path / domain_mo).is_file():
            return path
    return ordered[0] if ordered else Path("/usr/share/locale")


def normalize_language(value: object) -> str:
    raw = str(value or LANGUAGE_SYSTEM).strip().lower().replace("-", "_")
    if raw in {"", LANGUAGE_SYSTEM, "default", "auto"}:
        return LANGUAGE_SYSTEM
    if raw in {LANGUAGE_ENGLISH, "en_us", "en_gb", "english"}:
        return LANGUAGE_ENGLISH
    return LANGUAGE_SYSTEM


def language_choices() -> tuple[tuple[str, str], ...]:
    """Settings combo: real catalogs only (System default + English)."""
    return (
        (LANGUAGE_SYSTEM, _("System default")),
        (LANGUAGE_ENGLISH, _("English")),
    )


def apply_language_env(language: str) -> None:
    """Force English catalogs, or drop our override so System default uses the OS locale."""
    code = normalize_language(language)
    if code == LANGUAGE_ENGLISH:
        os.environ["LANGUAGE"] = "en_US:en"
        os.environ["LC_MESSAGES"] = "en_US.UTF-8"
        return
    os.environ.pop("LANGUAGE", None)
    if os.environ.get("LC_MESSAGES") == "en_US.UTF-8":
        os.environ.pop("LC_MESSAGES", None)


def install(language: str | None = None) -> gettext.NullTranslations:
    """Bind the GNU gettext domain before GTK widgets are built."""
    global _translation
    code = normalize_language(language if language is not None else load_config().get("language"))
    apply_language_env(code)
    try:
        locale_mod.setlocale(locale_mod.LC_ALL, "")
    except locale_mod.Error:
        pass
    localedir = str(locale_dir())
    gettext.bindtextdomain(GETTEXT_DOMAIN, localedir)
    gettext.textdomain(GETTEXT_DOMAIN)
    bind = getattr(locale_mod, "bindtextdomain", None)
    textdomain = getattr(locale_mod, "textdomain", None)
    if callable(bind):
        bind(GETTEXT_DOMAIN, localedir)
    if callable(textdomain):
        textdomain(GETTEXT_DOMAIN)
    languages = ["en"] if code == LANGUAGE_ENGLISH else None
    _translation = gettext.translation(
        GETTEXT_DOMAIN,
        localedir=localedir,
        languages=languages,
        fallback=True,
    )
    return _translation
