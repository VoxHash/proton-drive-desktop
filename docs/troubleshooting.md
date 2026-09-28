# Troubleshooting

**Sign in required** — run `proton-drive auth login` and keep the browser flow open until it prints success. Or use Settings → the account page after signing in.

**Stuck on Loading** — another `proton-drive` download may be holding the session. Disable the My files folder in Settings or wait for that pass, then refresh.

**CLI not found** — set `PROTON_DRIVE_BIN` or pick the binary in Settings.

**Sync folder did not appear** — official CLI 0.8.0 cannot FUSE-mount. Enable Settings → Keep a local My files folder and pick a directory. The worker writes `~/.config/proton-drive-linux/sync-status.json`.

**Tray still shows a folder icon** — install icons with `make user-install`, then restart this GUI (`python3 scripts/proton-drive-linux`). KDE reads `io.github.voxhash.ProtonDriveLinux` from hicolor plus the StatusNotifierItem pixmap.

**Help does not open** — confirm https://proton.me/support/drive in a browser; the app uses `xdg-open` / GTK URI launcher.
