# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.14.0] — 2026-10-01

### Added

- Debian/Ubuntu `.deb` packaging (`packaging/debian/`, `make deb`): GUI only (Python, data, desktop/metainfo/icons/locales); Depends on GTK4 / libadwaita / python3-gi packages; does **not** ship `proton-drive` CLI
- GitHub Release workflow optionally attaches `proton-drive-desktop_<version>_all.deb` and its SHA-256 in `SHA256SUMS` (same optional pattern as AppImage)
- Installation docs cover `.deb` install (`dpkg -i`) and remove (`dpkg -r`); `install.sh` apt user-install path unchanged

## [1.13.1] — 2026-09-30

### Added

- `make user-uninstall`, `scripts/uninstall.sh`, and `./install.sh --uninstall` remove the user-install payload under `~/.local` (binary, lib tree, desktop entry, AppStream metainfo, hicolor icons, locale `.mo` files), plus XDG autostart and optional systemd user sync units when present
- Uninstall flags `--purge` (delete `~/.config/proton-drive-desktop`) and `--remove-cli` (delete `~/.local/bin/proton-drive`); defaults leave both alone
- Installation docs cover uninstall and applications-menu paths (`Name=Proton Drive`, `io.github.voxhash.ProtonDriveDesktop`)

### Fixed

- Guided setup no longer crashes: `Adw.MessageDialog.present()` is called without a parent argument (transient parent remains set in the constructor), matching other message dialogs
- `make user-install` rewrites the installed `.desktop` `Exec=` / `TryExec=` to the absolute `~/.local/bin/proton-drive-desktop` path and refreshes the icon cache so desktop menus that check `TryExec` without `~/.local/bin` on `PATH` still show **Proton Drive**

## [1.13.0] — 2026-09-30

### Changed

- Renamed package, Python module, binary, AppStream id, gettext domain, and config dir from `proton-drive-linux` / `ProtonDriveLinux` to **`proton-drive-desktop`** / **`ProtonDriveDesktop`** (`io.github.voxhash.ProtonDriveDesktop`); config migrates from the legacy path when present
- Distribution install paths and docs focus on GitHub Releases, `install.sh`, and optional AppImage (AUR/Flathub remain roadmap, unpublished)

### Added

#### Engagement

- Multi-folder sync pairs (local ↔ `/my-files/...`; Settings add/remove/edit; legacy single folder migrates into the first pair)
- Pause / resume always-on sync from Settings and the system tray (`sync_paused`)
- Richer Activity history: bounded recent passes with pull / push / skip / error / timeout notes in `sync-status.json`
- Guided setup / welcome flow: CLI SHA-512 verify, preview, seed / assume-synced, enable always-on (`setup_completed`)
- Docs walkthrough: [docs/examples/example-02.md](docs/examples/example-02.md); interop pointers for FUSE / rclone / TrueNAS / Home Assistant (link-only, not productized)

#### Desktop UX parity

- Drag-and-drop upload onto My files
- Transfer progress (best-effort CLI spinner scrape) and in-memory transfer queue with cancel of the owned process tree
- In-list search (Ctrl+F), clickable breadcrumbs, list/grid toggle with extension-aware icons
- Multi-select bulk trash / download / move; read-only Properties dialog
- Remember window size and last-visited folder; desktop notifications when the always-on worker fails or auth expires

#### Always-on sync quality

- Exclude patterns (gitignore-style), selective remote root, dry-run / preview before enable
- Explicit conflict policy, configurable sync interval, bidirectional / upload-only / download-only direction
- Optional systemd user timer and path trigger (inotify / systemd.path) for sooner passes after local edits
- Local delta tracking, retry with backoff, optional per-pass timeout watchdog
- Seed / assume already synced on first enable

#### Distribution and safety

- GitHub Releases workflow: source tarball + `SHA256SUMS` on `v*` tags; optional AppImage (GUI only; never vendors `proton-drive`)
- `install.sh`: distro GTK deps, `make user-install`, optional CLI download only after Proton SHA-512 verify
- `make test-offline` / CI packaging smoke; CLI binary verify warn-before-use; threat model in SECURITY.md

### Documentation

- README badges (Release, CI), clear Releases / AppImage / `install.sh` paths
- FAQ / Usage / Architecture interop section (FUSE, rclone, TrueNAS, HA — recipes and links only)
- ROADMAP: engagement / UX / sync / safety / distribution items marked done; “Out of scope” block removed

## [1.12.0] — 2026-09-28

- Complete gettext catalogs for Russian (`ru`), Simplified Chinese (`zh_CN`), Arabic (`ar`), Italian (`it`), Portuguese (`pt`), Spanish (`es`), Korean (`ko`), and Japanese (`ja`)
- Settings → Language lists System default, English, and each language in its native name; the choice is saved in `gui.json` and restarts this Gio app so strings reload
- Arabic sets GTK widget direction to right-to-left. Portuguese uses gettext locale `pt` (not a separate `pt_BR`) so `LANGUAGE=pt` and `pt_BR` both load one catalog

## [1.11.0] — 2026-09-28

- GNU gettext for the GTK UI: `_()` / `ngettext()`, `po/en.po`, and `make user-install` compiles and installs the English `.mo`
- Settings → Language matches Proton Drive (System default or English). Changing language saves `gui.json` and restarts this Gio app so strings reload

## [1.10.0] — 2026-09-28

- Settings and About show the official CLI version from live `proton-drive version`, including whether Proton reports a newer CLI, with Download / CLI Help links to proton.me when an update exists (no Proton binary is downloaded into this repo)

## [1.9.0] — 2026-09-28

- Settings always-on folder activity: live worker running/stopped, last successful pass, files copied last pass, and last error from the niced `python3 -m proton_drive_desktop.sync` lock and `~/.config/proton-drive-desktop/sync-status.json` (official CLI has no Activity log)

## [1.8.0] — 2026-09-28

- Permanent per-item delete in Trash (`proton-drive filesystem delete`) with a destructive confirmation; Empty trash remains bulk-only

## [1.7.0] — 2026-09-28

- Photos albums: create, rename, delete, add photo, and remove photo from the GUI (`proton-drive album create|update|delete|add-photo|remove-photo`)

## [1.6.0] — 2026-09-28

- Settings always-on folder: enable starts the niced CLI download/upload worker immediately, keeps the chosen path, and turns on session autostart so the local folder stays on after login (still not FUSE)

## [1.5.0] — 2026-09-28

- Local My files folder in Settings: official CLI 0.8.0 still cannot FUSE-mount Drive, so a separate niced process skip/merge-copies `/my-files` into a user-chosen directory and uploads new local children without blocking the file list

## [1.4.0] — 2026-09-28

- Rename, Copy, and Move from the toolbar and right-click menu (`proton-drive filesystem rename|copy|move`)
- Empty trash from Trash with a destructive confirmation (`proton-drive filesystem empty-trash`)

## [1.3.0] — 2026-09-28

- Share from the toolbar: invite by email (`proton-drive sharing invite`), members and pending invites (`sharing status` / `sharing remove`), public links (`sharing set-url` / `sharing remove-url`), leave a share (`sharing leave`)
- Pending invitations in Shared with me from live `proton-drive invitation list`, with Accept / Reject (`invitation accept` / `invitation reject`)

## [1.2.0] — 2026-09-28

- Primary menu with Settings and Help, mapped to official Drive (Help opens https://proton.me/support/drive; Settings uses the live CLI session)
- Official Proton Drive launcher artwork for the window, .desktop file, hicolor icons, and tray StatusNotifierItem
- `make user-install`, AppStream metainfo, and an Arch PKGBUILD so a source install is a real desktop app

## [1.1.0] — 2026-09-28

- System tray via StatusNotifierItem / DBusMenu (Show, Hide, Open My files, Quit); closing the window hides to tray
- Photos timeline from the official `proton-drive photo timeline` and `album list` CLI, with live JSON

## [1.0.0] — 2026-09-28

- First GTK4 GUI for Proton's official Drive CLI on Linux
- Live account listing, upload/download, trash, new folder

[1.14.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.14.0
[1.13.1]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.13.1
[1.13.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.13.0
[1.12.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.12.0
[1.11.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.11.0
[1.10.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.10.0
[1.9.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.9.0
[1.8.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.8.0
[1.7.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.7.0
[1.6.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.6.0
[1.5.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.5.0
[1.4.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.4.0
[1.3.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.3.0
[1.2.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.2.0
[1.1.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.1.0
[1.0.0]: https://github.com/VoxHash/proton-drive-desktop/releases/tag/v1.0.0
