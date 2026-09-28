# Roadmap

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
- [ ] Album management in Photos (`proton-drive album create|update|delete|add-photo|remove-photo`; list/timeline already ship)
- [ ] Permanent per-item delete in the UI (`proton-drive filesystem delete`; Empty trash already covers bulk)
- [ ] Always-on folder activity in Settings (worker status, last pass, errors — CLI has no Windows-style Activity log)
- [ ] Surface official CLI update check (`proton-drive version` already reports latest vs newer)
- [ ] English gettext / i18n for this GTK UI (Proton Windows/macOS language settings; this app is English-only)
- [ ] Publish the existing Arch PKGBUILD to the AUR (do not bundle Proton’s prebuilt CLI)
- [ ] Flathub listing (CLI must stay an extra runtime the user installs; do not redistribute proton.me binaries)
- [ ] Adopt official CLI `mount` / Proton Sync if they ship it
- [ ] Replace with Proton's official Linux GUI when they ship it

## True FUSE verdict (2026-09-28)

**Do not fork Proton Drive CLI. Do not add a FUSE daemon in this Python/GTK repo.** Keep the always-on folder. Wait for official Linux Drive (GUI and/or `mount` / SDK Sync).

| Question | Verdict |
| --- | --- |
| Is a CLI fork required to add True FUSE? | **No.** 0.8.0 is 46 days old, Proton is shipping Linux Drive tooling, and they already promised a Linux desktop client with sync. |
| Can True FUSE be added natively here by wrapping `list`/`download`/`upload`? | **No.** That is still a new FUSE filesystem daemon talking to Proton APIs, not a GTK feature. |
| Can this repo call the MIT SDK from a FUSE process using the signed-in session, without SRP? | **Technically possible, not viable now.** Session is in libsecret `ch.proton.drive/drive-sdk-cli`. The SDK is MIT on npm. A FUSE daemon would still be a large new product, fight the CLI for the session, and sit on an SDK Proton has not released for third-party apps. |

### Dates and sources

- **CLI 0.8.0 released 2026-08-13** (46 days before 2026-09-28) on [proton.me/download/drive/cli](https://proton.me/download/drive/cli/index.html). Git tag [`cli/v0.8.0`](https://github.com/ProtonDriveApps/sdk/commit/5491f2eea473acaaa86b5969774b84610a37bd46) is 2026-08-12 (`feat(cli-js)!: clarify conflict strategies`). Repology recorded AUR 0.8.0 on 2026-08-13; winget `Proton.ProtonDrive.CLI` 0.8.0 lists the same day.
- **Local binary (2026-09-28):** `cli-drive@0.8.0+06e8c605`, SDK `js@0.21.0+06e8c605`, `You are running the latest version.` No `mount` in `proton-drive --help`. Same command set as [proton.me/support/drive-cli](https://proton.me/support/drive-cli). CLI is not on PyPI; install is the proton.me Bun binary or `bun run build` from source.
- **SDK is active, not stale:** [ProtonDriveApps/sdk](https://github.com/ProtonDriveApps/sdk) last commits 2026-09-24 (`feat(client-js): add recently accessed APIs`). npm [`@protontech/drive-sdk`](https://www.npmjs.com/package/@protontech/drive-sdk) **0.21.3** published 2026-09-25 (MIT). CLI 0.8.0 still embeds **js@0.21.0**.
- **Licenses:** SDK + CLI **source** are MIT ([LICENSE.md](https://github.com/ProtonDriveApps/sdk/blob/HEAD/LICENSE.md), copyright Proton AG 2025–2026). Access to Proton’s hosted Drive is still under Proton ToS. **Do not redistribute** the proton.me prebuilt `proton-drive` binary from this repo. Forks of the CLI must set `CLI_APP_VERSION_NAME`; official builds use `cli-drive` ([cli/README.md](https://github.com/ProtonDriveApps/sdk/blob/main/cli/README.md)).
- **Session without redoing SRP:** After `proton-drive auth login`, credentials live in the OS secret store under service `ch.proton.drive/drive-sdk-cli` (documented in that README). This GUI already reuses that session by exec’ing the official CLI. It does not implement SRP.
- **Proton Linux GUI / FUSE:** June 9 2026 CLI announcement: *“a full-featured desktop client with sync is on its way”* ([proton.me/blog/proton-drive-cli](https://proton.me/blog/proton-drive-cli)). January 2026 SDK update: *“Build a Linux client using the SDK”* ([proton.me/blog/drive-sdk-january-2026](https://proton.me/blog/drive-sdk-january-2026)). SDK README lists a **Sync** module as *Coming soon*, and says the SDK is **not yet officially released for third-party use**. Crypto model change is targeted **end of 2026 / early 2027**; older clients would stop interoperating. No Proton announcement of Linux FUSE or `mount`. Windows/macOS desktop apps use Explorer/Finder sync, not a Linux FUSE mount ([proton.me/support/proton-drive-windows-app](https://proton.me/support/proton-drive-windows-app)).
- **Out of scope:** rclone `protondrive`, unofficial FUSE clients, CAPTCHA/password login clones.

### Why not fork or ship FUSE here

0.8.0 is weeks old, not years. Proton is still cutting CLI releases (0.4.x in June 2026 through 0.8.0 on 13 August) and pushing SDK commits days before this note. The official path is their Linux GUI plus the forthcoming SDK Sync module, not a community FUSE fork. A Python in-process `list`/`download`/`upload` loop is the always-on folder we already ship; calling that a mount would be false. Wiring `@protontech/drive-sdk` from Bun/Node into fusermount would be a new daemon, session-contended with the CLI (the GUI already waits on downloads), and unsupported as a third-party integration. Revisit only after Proton’s Linux client ships **without** a mount/sync story and CLI `help` still has no `mount`.

## Parity notes (Windows / macOS / web)

Ship in this wrapper only when the official CLI already exposes the command. Blocked until Proton adds CLI/SDK support: account storage quota, Windows Activity feed, Docs, version history UI, Optimize Storage, devices / Other computers, Google Photos import, Finder/Explorer placeholder files, auto-update of Proton’s own GUI.

rclone `protondrive` and unofficial FUSE clients stay out of scope. The shipped path is a user-chosen always-on folder, not a fake mount.
