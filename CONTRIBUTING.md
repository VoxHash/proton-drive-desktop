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

UI strings use GNU gettext. After changing `_()` / `ngettext()` calls, run `make update-po` then keep `po/en.po` complete (English `msgstr` matching `msgid`). `make user-install` compiles `po/en.po` to `~/.local/share/locale/en/LC_MESSAGES/proton-drive-linux.mo`.

## Pull requests

Use conventional commits (`feat`, `fix`, `docs`, `chore`). Keep diffs small.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
