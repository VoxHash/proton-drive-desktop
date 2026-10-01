# FAQ

**Is this official?** No. Proton's Linux Drive GUI is unreleased. This wraps their official CLI.

**Does this app store my Proton password?** No. The Proton account password never enters this process. Sign-in is `proton-drive auth login` (browser); the official CLI keeps the session in the OS keyring. An optional **public link** password in Share is only for `sharing set-url`, not account login. See [SECURITY.md](../SECURITY.md).

**Does it sync like Windows?** Official CLI 0.8.0 still cannot FUSE-mount Drive and has no Activity log. Settings can keep an always-on folder updated with skip/merge `filesystem download` / `upload` in a separate process. That is a real directory, not a mount. Settings shows this app's worker activity (running/stopped, last pass, errors) from `sync-status.json`.

**Where is Help?** Primary menu → Proton Drive Help, which opens https://proton.me/support/drive.

**How do I change the language?** Settings → Language. Options are System default (OS locale), English, and complete catalogs for Russian, Simplified Chinese, Arabic, Italian, Portuguese, Spanish, Korean, and Japanese (shown as native names). Changing language writes `language` in `~/.config/proton-drive-desktop/gui.json` and restarts this Gio app. Arabic uses a right-to-left GTK layout. Portuguese is gettext locale `pt` so `pt_BR` loads the same catalog.

**How do I update the official CLI?** Settings → CLI version / CLI updates runs live `proton-drive version`. If Proton reports a newer CLI, Download opens https://proton.me/download/drive/cli and CLI Help opens https://proton.me/support/drive-cli. This app does not download or replace Proton’s binary. About shows the same check.

**Why isn’t the always-on folder a FUSE mount?** Live `proton-drive --help` and ProtonDriveApps/sdk have no `mount` command. This repo does not ship FUSE or rclone. Optional third-party stacks you can install separately (link only; not forked here): [khaosdoctor/proton-drive-linux-fs](https://github.com/khaosdoctor/proton-drive-linux-fs) (FUSE), [stektus/monti](https://github.com/stektus/monti) (rclone GUI mounts), [tibo-develop/proton-drive-sync-for-linux](https://github.com/tibo-develop/proton-drive-sync-for-linux) (rclone bisync). See [Usage](usage.md#interop-not-replace).

**Where is my storage quota in Settings?** Unavailable for now. Live official CLI 0.8.0 `--help` has no `quota`, `storage`, `usage`, or `account` command (only `auth`, `filesystem`, `sharing`, `invitation`, `album`, `photo`). Settings → **Storage quota** probes that help text and shows Unavailable — this app never invents used/total numbers. When Proton adds a public CLI command, the watch item in [ROADMAP.md](../ROADMAP.md) can grow a real UI.

**Can I install it like Proton Pass or Proton VPN?** Pass is Flathub (`me.proton.Pass`). VPN is Arch extra (`pacman -S proton-vpn-gtk-app`). This app uses `./install.sh`, `make user-install`, or an optional Debian/Ubuntu `.deb` from GitHub Releases, plus a separate official CLI on PATH (source tarball + SHA256SUMS; optional AppImage / `.deb` still need host GTK and `proton-drive`). There is no Flathub listing yet.

**How do I set up multiple always-on folders?** Settings → Always-on → Sync pairs (add/edit/remove). Each pair is a local directory ↔ a `/my-files/...` remote root. Guided setup on first launch covers checksum, preview, seed, and enable. Pause sync from Settings or the tray without turning always-on off. Activity (recent passes) is in the same Settings group. Step-by-step: [examples/example-02.md](examples/example-02.md).

**Does this replace FUSE, rclone, TrueNAS, or Home Assistant backups?** No — **interop, not replace**. This app is a GTK GUI + always-on skip/merge worker over the official CLI. For a FUSE mount, rclone bisync, TrueNAS cron one-way UP, or HA Supervisor snapshot retention, install those projects yourself and keep them out of this repo’s process tree. Link table: [Usage — Interop](usage.md#interop-not-replace). On a desktop, upload-only direction + excludes + selective remote root often covers the same *folder* job TrueNAS scripts target, without packaging a NAS cron unit here.
