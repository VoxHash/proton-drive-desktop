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
proton-drive filesystem rename PATH NEW_NAME
proton-drive filesystem copy [-n NAME] SOURCE TARGET_PARENT
proton-drive filesystem move SOURCE TARGET_PARENT
proton-drive filesystem empty-trash
proton-drive photo timeline -j
proton-drive album list -j
proton-drive album photos ALBUM -j
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
```

Always-on local folder (not a FUSE mount; separate process):

```bash
python3 -m proton_drive_linux.sync --once
python3 -m proton_drive_linux.sync --force
python3 -m proton_drive_linux.sync --status
```

CLI commands not in the GUI yet: `filesystem delete` (permanent per-item delete; Empty trash covers bulk), `album create|update|delete|add-photo|remove-photo`. Official CLI 0.8.0 has no `mount` / FUSE command.
