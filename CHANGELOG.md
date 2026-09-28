# Changelog

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
