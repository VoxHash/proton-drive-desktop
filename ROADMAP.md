# Roadmap

## Done

- [x] GTK4 GUI over official CLI
- [x] My files / Shared with me / Trash
- [x] Upload, download, mkdir, trash
- [x] System tray (StatusNotifierItem)
- [x] Photos timeline
- [x] Help and Settings (official Drive Help, live CLI account/config)
- [x] Official Proton Drive app and tray icon
- [x] Desktop + AppStream + `make user-install` / Arch PKGBUILD
- [x] Sharing invites from the UI (`proton-drive sharing` / `invitation`)
- [x] Rename, copy, move, empty trash in the UI (CLI already has these)
- [x] Always-on local folder in Settings (enable, path, autostart the niced CLI worker; official CLI 0.8.0 has no FUSE `mount`)
- [x] Album management in Photos (`proton-drive album create|update|delete|add-photo|remove-photo`; list/timeline already ship)
- [x] Permanent per-item delete in the UI (`proton-drive filesystem delete`; Empty trash already covers bulk)
- [x] Always-on folder activity in Settings (worker status, last pass, errors — CLI has no Windows-style Activity log)
- [x] Surface official CLI update check (`proton-drive version` already reports latest vs newer)
- [x] English gettext / i18n for this GTK UI (Proton Windows/macOS language settings)
- [x] ru, zh_CN, ar, it, pt, es, ko, and ja catalogs (native names in Settings; Arabic RTL)



## Priority: engagement (multi-folder, pause, guided setup)

- [x] Multi-folder sync pairs (local folder ↔ `/my-files/...`; Settings add/remove/edit; migrate legacy single folder)
- [x] Pause / resume always-on sync (Settings + tray)
- [x] Richer Activity history (bounded last N passes with pull/push/skip/error/timeout notes)
- [x] Guided setup / welcome flow (CLI checksum, preview, seed/assume-synced, enable always-on)



## Priority: distribution (ship like Pass / VPN)

- [x] GitHub Releases with source tarball + SHA-256 checksums (parity with `pdrive-desktop` / AppImage-capable rivals)
- [x] Optional AppImage build that still requires a system `proton-drive` on PATH (do not vendor Proton binaries)
- [x] One-shot `install.sh`: system GTK deps, desktop launcher, optional CLI download only after verifying Proton’s published SHA-512 (see `protondrive-gui` / `pdrive-desktop`)
- [x] Debian/Ubuntu `.deb` (`make deb` / Release asset): GUI only; Depends on distro GTK/PyGObject; never vendors `proton-drive` CLI
- [ ] **AUR**: publish existing `packaging/arch/PKGBUILD` (GUI only; do not bundle Proton’s prebuilt CLI)
- [ ] **Flathub**: listing where `proton-drive` stays a user-installed extra runtime (do not redistribute proton.me binaries)



## Priority: desktop UX parity

- [x] Drag-and-drop upload onto the file view (files and folders in My files)
- [x] Transfer progress for upload/download (best-effort scrape of CLI spinner text until Proton ships JSON progress)
- [x] In-memory transfer queue with one active CLI process and cancel of the owned process tree
- [x] In-list search / filter (Ctrl+F) over the current folder listing
- [x] Clickable breadcrumb trail for the current remote path
- [x] List / grid view toggle with extension-aware file-type icons
- [x] Multi-select bulk trash / download / move
- [x] Read-only Properties dialog (name, type, size, modified, share status, full path)
- [x] Remember window size and last-visited folder across launches
- [x] Desktop notifications (`notify-send`) when the always-on worker fails or auth expires



## Priority: always-on sync quality

- [x] Sync exclude patterns (gitignore-style globs) for the always-on folder
- [x] Selective remote root (sync a chosen `/my-files/...` subtree, not only the whole tree)
- [x] Dry-run / preview pass before the first enable or after path changes (show upload/download counts; no destructive deletes)
- [x] Explicit conflict policy in Settings (keep skip/merge defaults; surface rename vs skip clearly)
- [x] Optional systemd user unit for the sync worker alongside XDG autostart
- [x] Configurable sync interval in Settings (today fixed at 300s in `sync.py`)
- [x] Optional sync direction in Settings: bidirectional (default), upload-only, or download-only (one-way UP is what TrueNAS scripts need; desktop keeps two-way as default)
- [x] Local delta tracking (mtime/size or content fingerprint) so a pass skips unchanged files instead of re-touching every child each interval
- [x] Retry with backoff for transient CLI / network failures during a sync pass (idempotent trash/create when the remote is already gone or already exists)
- [x] Optional per-pass timeout / watchdog so a hung CLI transfer cannot block the worker forever
- [x] Optional local path trigger (inotify or systemd path unit) to run a pass soon after edits under the always-on folder, not only on the fixed interval
- [x] Seed / “assume already synced” on first enable (record current local+remote state and skip the initial bulk upload when the user says both sides already match)



## Priority: safety and packaging hygiene

- [x] Verify `proton-drive` binary against Proton’s published SHA-512 before first Settings / first sync use (warn, do not auto-replace)
- [x] Document threat model and “no password in this process” guarantees (inspired by `pdrive-desktop`; keep MIT scope)
- [x] CI: packaging smoke + existing `tests/test_*.py` on every PR



## Remaining (blocked or publish work)

| Item | Status |
| --- | --- |
| AUR publish (`packaging/arch/PKGBUILD`) | Open — PKGBUILD exists; not submitted |
| Flathub listing | Open — CLI must remain external |
| Storage / quota watch in Settings | Blocked — official CLI 0.8.0 has no quota/storage/usage API |
| Official CLI `mount` / Proton Sync | Blocked — wait for Proton |
| Official Proton Linux GUI | Blocked — replace this app when Proton ships it |

## Priority: watch Proton / ecosystem (do not reimplement)

- [ ] Adopt official CLI `mount` / Proton Sync if they ship it
- [ ] Replace with Proton's official Linux GUI when they ship it
- [x] Document optional interoperability with external FUSE / rclone / TrueNAS / Home Assistant — link and recipe pointers only; do not fork or productize those niches (see `docs/usage.md#interop-not-replace`, `docs/faq.md`, `docs/architecture.md`, README)
- [ ] Account / storage quota UI if/when the official CLI exposes it — **blocked on Proton**: live `proton-drive` 0.8.0 `--help` has no `quota` / `storage` / `usage` / `account` command; Settings → Storage quota shows Unavailable after probing help; no fake used/total numbers

