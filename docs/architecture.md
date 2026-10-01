# Architecture

GTK4 window → background thread → official `proton-drive` JSON CLI → OS keyring session.

No Proton API is reimplemented. When Proton ships a Linux Drive app, this GUI should be retired.

## Security guarantees (process boundary)

```text
User → GTK GUI / sync worker → official proton-drive CLI → Proton Drive
                                      └→ OS keyring (CLI session)
```

- This GUI and the always-on worker never collect or persist the Proton **account** password. Sign-in is `proton-drive auth login` (browser); the CLI owns the keyring session.
- CLI invocations use an argv list (no shell). Optional public-link passwords for `sharing set-url` are link secrets only, not the account password.
- Before first Settings / first sync use, `cli_verify` may warn if the on-disk binary does not match Proton’s published SHA-512; it does not replace the binary.
- Desktop alerts use `notify-send`. Crypto and Drive protocol stay in Proton’s CLI — this project does not reinvent them.

Full threat model, reporting contact, and residual risks: [SECURITY.md](../SECURITY.md).

The window, `.desktop` file, hicolor theme, and StatusNotifierItem tray use Proton’s official Drive launcher mark from `ProtonDriveApps/android-drive`.

The always-on folder worker is a separate niced `python3 -m proton_drive_desktop.sync` process. It never runs `filesystem download` on the GTK thread, and it waits while the window is listing files unless the user clicks Sync now. Each pass writes `~/.config/proton-drive-desktop/sync-status.json` and holds `sync.lock` while running. Settings reads that file and the lock every two seconds for Worker / last pass / last error. Official `proton-drive` has no Activity log. XDG autostart launches the GUI; an optional systemd user oneshot service + timer (`proton-drive-desktop-sync.{service,timer}`) can schedule the same `--once` pass on the Settings sync interval (default 300s) via `systemctl --user` without replacing XDG. Optional Settings → Sync soon after local edits installs a debounced recursive Gio/inotify tree watch in the GUI and may enable `proton-drive-desktop-sync.path` (`PathChanged`/`PathModified` on the sync root and immediate child directories — systemd has no recursive path units) so edits can schedule a pass sooner than the fixed interval via a `sync-path-request` stamp that `due_for_pass` honors; changing the always-on folder rewrites and restarts that path unit. Deep nested edits while the GUI is closed still wait for the interval. Settings → Assume already synced (also on first-enable preview) records current local+remote fingerprints into `sync-delta.json` via a real list — no transfer — so the next pass skips bulk upload/download when both sides already match.

Settings and About parse live `proton-drive version` (Proton fetches https://proton.me/download/drive/cli/version.json itself). This GUI only displays that result and links to Proton’s CLI download page; it does not fetch or store Proton binaries.

Settings → Storage quota probes live `proton-drive --help` via `cli_help_exposes_storage_quota`. CLI 0.8.0 lists no account/storage quota command, so the row stays Unavailable. This app does not scrape Proton account pages or invent used/total bytes.

## Interop, not replace (out of process)

This repository stays a GTK wrapper over the official CLI. It does not embed or fork FUSE/rclone clients, TrueNAS cron packages, or Home Assistant add-ons. Users who need those niches run them separately — link table in [Usage — Interop](usage.md#interop-not-replace):

- FUSE: https://github.com/khaosdoctor/proton-drive-linux-fs
- rclone GUI mounts: https://github.com/stektus/monti
- rclone bisync: https://github.com/tibo-develop/proton-drive-sync-for-linux
- TrueNAS one-way UP: https://github.com/F1VWdk/truenas-to-proton-sync
- HA snapshot backup: https://github.com/ashishdevasia/ha-proton-drive-backup

Those stacks keep their own auth and lifecycle. This app’s always-on folder remains a skip/merge poll worker (multi-pair, pause, Activity history), not a FUSE daemon or NAS appliance.

GTK UI strings go through GNU gettext (`proton_drive_desktop.i18n`, domain `proton-drive-desktop`). English is the source language (`po/en.po`). Settings → Language is System default (OS locale), English, or complete catalogs `ru`, `zh_CN`, `ar`, `it`, `pt`, `es`, `ko`, and `ja` (native names in the combo). Portuguese uses `pt` rather than `pt_BR` so `LANGUAGE=pt` and `pt_BR` load the same file. Changing language writes `language` in `gui.json` and `execv`s this Gio process so catalogs reload. Arabic calls `Gtk.Widget.set_default_direction(RTL)`. `make user-install` compiles and installs each `<lang>/LC_MESSAGES/proton-drive-desktop.mo`. Desktop and AppStream stay English.
