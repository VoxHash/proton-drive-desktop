# Usage

Launch `proton-drive-desktop`. Sidebar sections map to CLI paths `/my-files`, `/photos`, `/shared-with-me`, `/trash`. Enter opens a folder. Download writes to the folder in Settings (default `~/Downloads`). In **My files**, drag and drop local files or folders onto the file view to upload into the current remote folder (`filesystem upload`).

**Photos** lists albums from `proton-drive album list` above the capture-date timeline. New album (the folder-new toolbar button in Photos) runs `album create`. Rename an album with the toolbar, F2, or right-click (`album update -n`). Delete album asks for confirmation then runs `album delete -s` (photos stay in the timeline). Open a day, select a photo, then Copy / Add to album (`album add-photo` with `/photos/{uid}`). Inside an album, Remove from album or the trash button runs `album remove-photo`.

**Share** (toolbar) runs live `proton-drive sharing` on the selected file or folder: invite by email (viewer / editor / admin), list members and pending invites, create or remove a public link, stop sharing, or leave a share that was shared with you.

**Rename**, **Copy**, and **Move** (toolbar and right-click) run `proton-drive filesystem rename|copy|move`. Copy and Move open a folder picker over live `filesystem list`. F2 also renames. In **Trash**, Restore is the trash toolbar button. **Delete permanently** asks for confirmation then runs `filesystem delete` on the selected trashed item only. **Empty trash** asks for confirmation then runs `filesystem empty-trash` (permanently deletes `/trash` only, not Photos trash).

Pending invitations from `proton-drive invitation list` appear at the top of **Shared with me**. Open one to Accept or Reject (`invitation accept` / `invitation reject`).

Settings can enable an **always-on folder** (default `~/Proton Drive`). That is not a FUSE mount: official CLI 0.8.0 has no `mount` command. Enabling it starts a separate niced process (`filesystem download` then `filesystem upload` with skip/merge) and turns on session autostart so the worker stays on after login. Existing local and remote files are never replaced. Sync does not touch `/trash`. Settings shows live **Worker** (Off / Stopped / Running with pid), **Last successful pass**, **Files last pass**, and **Last error** from `~/.config/proton-drive-desktop/sync-status.json` and the worker lock. Official `proton-drive` has no Windows-style Activity log. Settings → **Sync interval** sets how often the worker polls (default 300s; 60–86400). Settings → **systemd user timer** is optional and runs the same `--once` worker via `systemctl --user` on that interval alongside XDG autostart (not a replacement). Settings → **Sync soon after local edits** is optional: after a short debounce it requests a pass when the always-on folder changes (recursive inotify while the app runs; optional systemd path unit for the folder root and immediate subfolders when `systemctl --user` is available — deep nested edits while the GUI is closed wait for the sync interval). Settings → **Assume already synced** (also offered on first enable) records current local and remote fingerprints into delta state via a real Drive list so the next pass skips bulk transfer when both sides already match.

The primary menu (hamburger) matches official Drive’s Help / Settings / About / account actions:

- **Settings** — live account email, Storage quota (Unavailable until the official CLI exposes a quota command; probed on open), CLI version vs Proton newer check and path, theme, language (System default, English, ru, zh_CN, ar, it, pt, es, ko, ja; restarts the app; Arabic RTL), download folder, always-on folder (enable, path, worker activity), XDG autostart, optional systemd user timer, sign out (`proton-drive auth logout`)
- **Proton Drive Help** — https://proton.me/support/drive
- **Drive CLI Help** — https://proton.me/support/drive-cli
- **Open Drive in browser** — https://drive.proton.me
- **Open always-on folder** — opens the local always-on folder
- **About** — this unofficial GUI, live `proton-drive version` (latest vs newer), plus Proton Terms and Privacy links from the Windows Drive About pane

## Guided setup, multi-folder pairs, pause, Activity

- **Guided setup** — first launch (or primary menu / Settings → Always-on → Guided setup): CLI SHA-512 verify, preview counts, optional seed / assume-already-synced, enable always-on. Walkthrough: [examples/example-02.md](examples/example-02.md).
- **Sync pairs** — Settings → Always-on → Sync pairs: multiple local folders ↔ `/my-files/...` roots; legacy single folder migrates into the first pair.
- **Pause / resume** — Settings → Pause sync, or tray **Pause sync** / **Resume sync** (`sync_paused`). Always-on stays enabled; the worker skips passes until resume.
- **Activity** — Settings shows Worker / last pass / files / errors plus bounded **Recent passes** from `sync-status.json` (not a Proton CLI Activity log).

## Interop, not replace

This desktop GUI and its always-on folder worker talk only to the official `proton-drive` CLI. They do **not** vendor, fork, or productize FUSE mounts, rclone stacks, TrueNAS cron packages, or Home Assistant add-ons. Use those separately when you need them (their own auth, packages, and risk model). Pointers only:

| Audience / need | Project | Link |
| --- | --- | --- |
| Kernel FUSE mount | `khaosdoctor/proton-drive-linux-fs` | https://github.com/khaosdoctor/proton-drive-linux-fs |
| Friendly rclone mount GUI | `stektus/monti` | https://github.com/stektus/monti |
| rclone bisync + systemd | `tibo-develop/proton-drive-sync-for-linux` | https://github.com/tibo-develop/proton-drive-sync-for-linux |
| TrueNAS / NAS one-way UP cron | `F1VWdk/truenas-to-proton-sync` | https://github.com/F1VWdk/truenas-to-proton-sync |
| Home Assistant snapshot backup | `ashishdevasia/ha-proton-drive-backup` | https://github.com/ashishdevasia/ha-proton-drive-backup |

**Recipes that stay in this app (no extra install):** upload-only or download-only direction, exclude globs, selective `/my-files/...` remote root, retry/timeout, seed / assume-synced, multi-folder pairs — see [Configuration](configuration.md). Those cover many TrueNAS-style one-way folder jobs on a desktop without adopting the NAS cron package.

Official CLI 0.8.0 still has no `mount` command. Running an external mount and this app’s always-on folder against the same local path at once is unsupported — pick one local sync approach per directory.
