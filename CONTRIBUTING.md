# Contributing

## Setup

```bash
python3 tests/test_cli.py
python3 tests/test_packaging.py
python3 tests/test_sync.py
python3 tests/test_i18n.py
python3 -m proton_drive_linux
```

Requires Proton's official `proton-drive` CLI and a signed-in session.

UI strings use GNU gettext. After changing `_()` / `ngettext()` calls, run `make update-po` then keep every `po/*.po` complete (`en` msgstr matches msgid; other locales must not leave English `msgstr`). `make user-install` compiles all catalogs under `LOCALES` to `~/.local/share/locale/<lang>/LC_MESSAGES/proton-drive-linux.mo`. Portuguese is `po/pt.po` (not `pt_BR`) so `LANGUAGE=pt` and `pt_BR` both load it. Arabic catalogs plus `Gtk.Widget.set_default_direction(RTL)` flip the GTK layout.

## Pull requests

Use conventional commits (`feat`, `fix`, `docs`, `chore`). Keep diffs small.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
