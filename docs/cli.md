# CLI

This GUI does not replace Proton's CLI. It runs:

```bash
proton-drive filesystem list PATH -j
proton-drive filesystem info PATH -j
proton-drive filesystem upload LOCAL... PARENT -f skip -d merge -t
proton-drive filesystem download REMOTE FOLDER -f skip -d merge
proton-drive filesystem create-folder PARENT NAME
proton-drive filesystem trash PATH
proton-drive filesystem restore PATH
proton-drive filesystem delete PATH
proton-drive filesystem rename PATH NEW_NAME
proton-drive filesystem copy [-n NAME] SOURCE TARGET_PARENT
proton-drive filesystem move SOURCE TARGET_PARENT
proton-drive filesystem empty-trash
proton-drive photo timeline -j
proton-drive album list -j
proton-drive album photos ALBUM -j
proton-drive album create NAME -j
proton-drive album update [-n NAME] [-c UID] ALBUM -j
proton-drive album delete [-f] [-s] ALBUM -j
proton-drive album add-photo ALBUM PHOTO... -j
proton-drive album remove-photo ALBUM PHOTO... -j
proton-drive photo download PATH FOLDER -c rename
proton-drive photo upload LOCAL... -c skip
proton-drive sharing status PATH -j
proton-drive sharing invite -u EMAIL -r ROLE PATH -j
proton-drive sharing remove [-e EMAIL...] [-a] PATH
proton-drive sharing leave PATH
proton-drive sharing set-url [--role ROLE] PATH -j
proton-drive sharing remove-url PATH
proton-drive invitation list -j
proton-drive invitation accept UID
proton-drive invitation reject UID
proton-drive auth login
proton-drive auth logout
proton-drive version
proton-drive version -j
```

`proton-drive version` prints the installed CLI/SDK labels and then either `You are running the latest version.` or `A newer version is available: X (you have Y).` plus `Download at https://proton.me/download/drive/cli/index.html`. The global `-j` flag is accepted but CLI 0.8.0 still prints that text (not JSON). `version --help` runs the same check rather than printing command help. Settings and About parse this output; they never download Proton binaries.

Always-on local folder (not a FUSE mount; separate process):

```bash
python3 -m proton_drive_desktop.sync --once
python3 -m proton_drive_desktop.sync --force
python3 -m proton_drive_desktop.sync --status
```

`--status` prints `~/.config/proton-drive-desktop/sync-status.json` (worker state, last success, last error, files copied). Settings reads the same file plus `sync.lock`. Official CLI 0.8.0 has no `mount` / FUSE command, no Activity log, and no account/storage quota command (`proton-drive --help` lists `auth`, `filesystem`, `sharing`, `invitation`, `album`, `photo` only). Settings → Storage quota probes that help text and shows Unavailable rather than inventing numbers. `filesystem delete` permanently removes one already-trashed item; `filesystem empty-trash` still clears all of `/trash`.

Extract GTK UI strings with `make pot` / `make update-po`. `make user-install` runs `msgfmt` and installs `en`, `ru`, `zh_CN`, `ar`, `it`, `pt`, `es`, `ko`, and `ja` under `LC_MESSAGES/proton-drive-desktop.mo`. Portuguese is `pt` so `LANGUAGE=pt_BR` still loads it.
