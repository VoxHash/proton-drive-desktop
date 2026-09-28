# Troubleshooting

**Sign in required** — run `proton-drive auth login` and keep the browser flow open until it prints success. Or use Settings → the account page after signing in.

**Stuck on Loading** — another `proton-drive` download may be holding the session. Disable the always-on folder in Settings or wait for that pass, then refresh.

**CLI not found** — set `PROTON_DRIVE_BIN` or pick the binary in Settings.

**CLI updates row is empty or unknown** — `proton-drive version` needs network access to Proton’s version.json. If that fetch fails, the CLI still prints its own version lines and Settings shows that it did not report latest or newer.

**A newer CLI is available** — Settings → Download opens https://proton.me/download/drive/cli. Replace the binary on this machine yourself. This GUI does not download Proton binaries.

**Always-on folder did not appear** — official CLI 0.8.0 cannot FUSE-mount. Enable Settings → Enable always-on folder and pick a directory. The worker writes `~/.config/proton-drive-linux/sync-status.json`. Open Settings to see Worker (running/stopped), last successful pass, files copied last pass, and last error.

**Always-on folder shows an error** — Settings → Last error is the last failure from this app's niced worker, not a Proton CLI Activity log. Fix the listed download/upload path, then Sync now.

**Tray still shows a folder icon** — install icons with `make user-install`, then restart this GUI (`python3 scripts/proton-drive-linux`). KDE reads `io.github.voxhash.ProtonDriveLinux` from hicolor plus the StatusNotifierItem pixmap.

**Language did not change** — Settings → Language writes `language` in `~/.config/proton-drive-linux/gui.json` and restarts this Gio process. System default follows the OS locale and falls back to English because only `po/en.po` ships. Desktop and AppStream stay English.

**Help does not open** — confirm https://proton.me/support/drive in a browser; the app uses `xdg-open` / GTK URI launcher.
