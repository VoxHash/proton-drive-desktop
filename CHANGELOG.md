# Changelog

## 1.12.0 — 2026-09-28

- Complete gettext catalogs for Russian (`ru`), Simplified Chinese (`zh_CN`), Arabic (`ar`), Italian (`it`), Portuguese (`pt`), Spanish (`es`), Korean (`ko`), and Japanese (`ja`)
- Settings → Language lists System default, English, and each language in its native name; the choice is saved in `gui.json` and restarts this Gio app so strings reload
- Arabic sets GTK widget direction to right-to-left. Portuguese uses gettext locale `pt` (not a separate `pt_BR`) so `LANGUAGE=pt` and `pt_BR` both load one catalog

## 1.11.0 — 2026-09-28

- GNU gettext for the GTK UI: `_()` / `ngettext()`, `po/en.po`, and `make user-install` compiles and installs the English `.mo`
- Settings → Language matches Proton Drive (System default or English). Changing language saves `gui.json` and restarts this Gio app so strings reload

## 1.10.0 — 2026-09-28

- Settings and About show the official CLI version from live `proton-drive version`, including whether Proton reports a newer CLI, with Download / CLI Help links to proton.me when an update exists (no Proton binary is downloaded into this repo)

## 1.9.0 — 2026-09-28

- Settings always-on folder activity: live worker running/stopped, last successful pass, files copied last pass, and last error from the niced `python3 -m proton_drive_linux.sync` lock and `~/.config/proton-drive-linux/sync-status.json` (official CLI has no Activity log)

## 1.8.0 — 2026-09-28

- Permanent per-item delete in Trash (`proton-drive filesystem delete`) with a destructive confirmation; Empty trash remains bulk-only

## 1.7.0 — 2026-09-28

- Photos albums: create, rename, delete, add photo, and remove photo from the GUI (`proton-drive album create|update|delete|add-photo|remove-photo`)

## 1.6.0 — 2026-09-28

- Settings always-on folder: enable starts the niced CLI download/upload worker immediately, keeps the chosen path, and turns on session autostart so the local folder stays on after login (still not FUSE)

## 1.5.0 — 2026-09-28

- Local My files folder in Settings: official CLI 0.8.0 still cannot FUSE-mount Drive, so a separate niced process skip/merge-copies `/my-files` into a user-chosen directory and uploads new local children without blocking the file list

## 1.4.0 — 2026-09-28

- Rename, Copy, and Move from the toolbar and right-click menu (`proton-drive filesystem rename|copy|move`)
- Empty trash from Trash with a destructive confirmation (`proton-drive filesystem empty-trash`)

## 1.3.0 — 2026-09-28

- Share from the toolbar: invite by email (`proton-drive sharing invite`), members and pending invites (`sharing status` / `sharing remove`), public links (`sharing set-url` / `sharing remove-url`), leave a share (`sharing leave`)
- Pending invitations in Shared with me from live `proton-drive invitation list`, with Accept / Reject (`invitation accept` / `invitation reject`)

## 1.2.0 — 2026-09-28

- Primary menu with Settings and Help, mapped to official Drive (Help opens https://proton.me/support/drive; Settings uses the live CLI session)
- Official Proton Drive launcher artwork for the window, .desktop file, hicolor icons, and tray StatusNotifierItem
- `make user-install`, AppStream metainfo, and an Arch PKGBUILD so a source install is a real desktop app

## 1.1.0 — 2026-09-28

- System tray via StatusNotifierItem / DBusMenu (Show, Hide, Open My files, Quit); closing the window hides to tray
- Photos timeline from the official `proton-drive photo timeline` and `album list` CLI, with live JSON

## 1.0.0 — 2026-09-28

- First GTK4 GUI for Proton's official Drive CLI on Linux
- Live account listing, upload/download, trash, new folder
