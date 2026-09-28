# FAQ

**Is this official?** No. Proton's Linux Drive GUI is unreleased. This wraps their official CLI.

**Does it sync like Windows?** Official CLI 0.8.0 still cannot FUSE-mount Drive and has no Activity log. Settings can keep an always-on folder updated with skip/merge `filesystem download` / `upload` in a separate process. That is a real directory, not a mount. Settings shows this app's worker activity (running/stopped, last pass, errors) from `sync-status.json`.

**Where is Help?** Primary menu → Proton Drive Help, which opens https://proton.me/support/drive.

**How do I change the language?** Settings → Language. Options are System default (OS locale, English catalog if the locale has no translation) and English. Changing language writes `language` in `~/.config/proton-drive-linux/gui.json` and restarts this Gio app. The UI is English-only until a complete extra catalog is added.

**How do I update the official CLI?** Settings → CLI version / CLI updates runs live `proton-drive version`. If Proton reports a newer CLI, Download opens https://proton.me/download/drive/cli and CLI Help opens https://proton.me/support/drive-cli. This app does not download or replace Proton’s binary. About shows the same check.

**Why isn’t the always-on folder a FUSE mount?** Live `proton-drive --help` and ProtonDriveApps/sdk have no `mount` command. rclone protondrive is out of scope.

**Can I install it like Proton Pass or Proton VPN?** Pass is Flathub (`me.proton.Pass`). VPN is Arch extra (`pacman -S proton-vpn-gtk-app`). This app installs with `make user-install` after the official CLI is on PATH. There is no Flathub listing yet.
