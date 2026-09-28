# FAQ

**Is this official?** No. Proton's Linux Drive GUI is unreleased. This wraps their official CLI.

**Does it sync like Windows?** Official CLI 0.8.0 still cannot FUSE-mount Drive. Settings can keep a local My files folder updated with skip/merge `filesystem download` / `upload` in a separate process. That is a real directory, not a mount.

**Where is Help?** Primary menu → Proton Drive Help, which opens https://proton.me/support/drive.

**Why isn’t the My files folder a FUSE mount?** Live `proton-drive --help` and ProtonDriveApps/sdk have no `mount` command. rclone protondrive is out of scope.

**Can I install it like Proton Pass or Proton VPN?** Pass is Flathub (`me.proton.Pass`). VPN is Arch extra (`pacman -S proton-vpn-gtk-app`). This app installs with `make user-install` after the official CLI is on PATH. There is no Flathub listing yet.
