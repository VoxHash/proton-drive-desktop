"""GNU gettext for the GTK UI. English is the source language."""

from __future__ import annotations

import gettext
import locale as locale_mod
import os
from pathlib import Path

from .config import load as load_config
from .paths import repo_root

GETTEXT_DOMAIN = "proton-drive-desktop"
LANGUAGE_SYSTEM = "system"
LANGUAGE_ENGLISH = "en"
SESSION_LANG = "PDL_SESSION_LANG"
SESSION_LANGUAGE = "PDL_SESSION_LANGUAGE"
SESSION_LC_MESSAGES = "PDL_SESSION_LC_MESSAGES"

# Native names stay in their own script. Portuguese uses gettext `pt` (not pt_BR)
# so LANGUAGE=pt and LANGUAGE=pt_BR both load one catalog.
_LANGUAGE_CATALOGS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("en", "English", "en_US.UTF-8", "en_US:en", False),
    ("ru", "Русский", "ru_RU.UTF-8", "ru_RU:ru", False),
    ("zh_CN", "简体中文", "zh_CN.UTF-8", "zh_CN:zh", False),
    ("ar", "العربية", "ar_EG.UTF-8", "ar_EG:ar", True),
    ("it", "Italiano", "it_IT.UTF-8", "it_IT:it", False),
    ("pt", "Português", "pt_PT.UTF-8", "pt:pt_BR:pt_PT", False),
    ("es", "Español", "es_ES.UTF-8", "es_ES:es", False),
    ("ko", "한국어", "ko_KR.UTF-8", "ko_KR:ko", False),
    ("ja", "日本語", "ja_JP.UTF-8", "ja_JP:ja", False),
)

SUPPORTED_LANGUAGES: tuple[str, ...] = (LANGUAGE_SYSTEM,) + tuple(code for code, *_rest in _LANGUAGE_CATALOGS)
CATALOG_CODES: tuple[str, ...] = tuple(code for code, *_rest in _LANGUAGE_CATALOGS)

_ALIASES: dict[str, str] = {
    LANGUAGE_SYSTEM: LANGUAGE_SYSTEM,
    "default": LANGUAGE_SYSTEM,
    "auto": LANGUAGE_SYSTEM,
    "en": "en",
    "en_us": "en",
    "en_gb": "en",
    "english": "en",
    "ru": "ru",
    "ru_ru": "ru",
    "russian": "ru",
    "zh": "zh_CN",
    "zh_cn": "zh_CN",
    "zh_hans": "zh_CN",
    "zh_sg": "zh_CN",
    "chinese": "zh_CN",
    "ar": "ar",
    "ar_eg": "ar",
    "ar_sa": "ar",
    "ar_ae": "ar",
    "arabic": "ar",
    "it": "it",
    "it_it": "it",
    "italian": "it",
    "pt": "pt",
    "pt_pt": "pt",
    "pt_br": "pt",
    "portuguese": "pt",
    "es": "es",
    "es_es": "es",
    "es_mx": "es",
    "spanish": "es",
    "ko": "ko",
    "ko_kr": "ko",
    "korean": "ko",
    "ja": "ja",
    "ja_jp": "ja",
    "japanese": "ja",
}

_translation = gettext.NullTranslations()
_active_language = LANGUAGE_SYSTEM


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)


def _catalog(code: str) -> tuple[str, str, str, str, bool] | None:
    for row in _LANGUAGE_CATALOGS:
        if row[0] == code:
            return row
    return None


def locale_dir(language: str | None = None) -> Path:
    """Directory that contains <lang>/LC_MESSAGES/<domain>.mo."""
    code = language if language in CATALOG_CODES else "en"
    domain_mo = Path(code) / "LC_MESSAGES" / f"{GETTEXT_DOMAIN}.mo"
    fallback_mo = Path("en") / "LC_MESSAGES" / f"{GETTEXT_DOMAIN}.mo"
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
    for path in ordered:
        if (path / fallback_mo).is_file():
            return path
    return ordered[0] if ordered else Path("/usr/share/locale")


def normalize_language(value: object) -> str:
    raw = str(value or LANGUAGE_SYSTEM).strip().replace("-", "_")
    if raw == "zh_CN":
        return "zh_CN"
    key = raw.lower()
    if key in {"", LANGUAGE_SYSTEM}:
        return LANGUAGE_SYSTEM
    return _ALIASES.get(key, LANGUAGE_SYSTEM)


def language_choices() -> tuple[tuple[str, str], ...]:
    """Settings combo: System default, English, then native names for each catalog."""
    rows: list[tuple[str, str]] = [
        (LANGUAGE_SYSTEM, _("System default")),
        (LANGUAGE_ENGLISH, _("English")),
    ]
    for code, native, *_rest in _LANGUAGE_CATALOGS:
        if code == LANGUAGE_ENGLISH:
            continue
        rows.append((code, native))
    return tuple(rows)


def snapshot_session_locale() -> None:
    os.environ.setdefault(SESSION_LANG, os.environ.get("LANG", ""))
    os.environ.setdefault(SESSION_LANGUAGE, os.environ.get("LANGUAGE", ""))
    os.environ.setdefault(SESSION_LC_MESSAGES, os.environ.get("LC_MESSAGES", ""))


def restore_session_locale_env() -> None:
    """Drop gettext overrides so a relaunch reads gui.json against the session locale."""
    lang = os.environ.get(SESSION_LANG, "")
    language = os.environ.get(SESSION_LANGUAGE, "")
    lc_messages = os.environ.get(SESSION_LC_MESSAGES, "")
    if lang:
        os.environ["LANG"] = lang
    else:
        os.environ.pop("LANG", None)
    if language:
        os.environ["LANGUAGE"] = language
    else:
        os.environ.pop("LANGUAGE", None)
    if lc_messages:
        os.environ["LC_MESSAGES"] = lc_messages
    else:
        os.environ.pop("LC_MESSAGES", None)


def apply_language_env(language: str) -> None:
    """Force a catalog, or restore the session locale for System default."""
    code = normalize_language(language)
    if code == LANGUAGE_SYSTEM:
        restore_session_locale_env()
        return
    spec = _catalog(code)
    if spec is None:
        restore_session_locale_env()
        return
    _code, _native, locale_name, language_env, _rtl = spec
    os.environ["LANGUAGE"] = language_env
    os.environ["LC_MESSAGES"] = locale_name
    os.environ["LANG"] = locale_name


def is_rtl(language: str | None = None) -> bool:
    code = normalize_language(language if language is not None else _active_language)
    if code == LANGUAGE_SYSTEM:
        env = (os.environ.get("LANGUAGE") or os.environ.get("LANG") or "").lower().replace("-", "_")
        return env.startswith("ar")
    spec = _catalog(code)
    return bool(spec and spec[4])


def apply_gtk_direction(language: str | None = None) -> None:
    """GTK follows LANG when the locale exists; always set widget direction for Arabic."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    Gtk.Widget.set_default_direction(
        Gtk.TextDirection.RTL if is_rtl(language) else Gtk.TextDirection.LTR
    )


def active_language() -> str:
    return _active_language


def install(language: str | None = None) -> gettext.NullTranslations:
    """Bind the GNU gettext domain before GTK widgets are built."""
    global _translation, _active_language
    snapshot_session_locale()
    code = normalize_language(language if language is not None else load_config().get("language"))
    _active_language = code
    apply_language_env(code)
    locale_name = ""
    spec = _catalog(code)
    if spec is not None:
        locale_name = spec[2]
    try:
        if locale_name:
            locale_mod.setlocale(locale_mod.LC_MESSAGES, locale_name)
        else:
            locale_mod.setlocale(locale_mod.LC_ALL, "")
    except locale_mod.Error:
        try:
            locale_mod.setlocale(locale_mod.LC_ALL, "")
        except locale_mod.Error:
            pass
    localedir = str(locale_dir(code if code != LANGUAGE_SYSTEM else None))
    gettext.bindtextdomain(GETTEXT_DOMAIN, localedir)
    gettext.textdomain(GETTEXT_DOMAIN)
    bind = getattr(locale_mod, "bindtextdomain", None)
    textdomain = getattr(locale_mod, "textdomain", None)
    if callable(bind):
        bind(GETTEXT_DOMAIN, localedir)
    if callable(textdomain):
        textdomain(GETTEXT_DOMAIN)
    languages = None if code == LANGUAGE_SYSTEM else [code]
    _translation = gettext.translation(
        GETTEXT_DOMAIN,
        localedir=localedir,
        languages=languages,
        fallback=True,
    )
    return _translation
