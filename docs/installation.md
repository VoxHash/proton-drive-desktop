# Installation

Dependencies: GTK 4, libadwaita, Python 3.12+, official `proton-drive` CLI 0.8.0, libsecret.

On Garuda/Arch:

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita gdk-pixbuf2 libsecret
```

Official CLI (not bundled):

```bash
# from https://proton.me/download/drive/cli  or AUR proton-drive-cli / proton-drive-cli-bin
proton-drive auth login
proton-drive version
```

Install this GUI for the current user:

```bash
cd ~/Projects/proton-drive-linux
make user-install
proton-drive-linux
```

System-wide:

```bash
sudo make PREFIX=/usr/local install
```

Arch packaging (AUR-ready, not published): `packaging/arch/PKGBUILD`. It installs the GUI only; install the CLI from AUR or Proton’s download page.

Verify after install:

```bash
python3 tests/test_cli.py
python3 tests/test_packaging.py
python3 tests/test_sync.py
python3 tests/test_i18n.py
```

This is not a Flatpak. Proton Pass on this machine is `flatpak install flathub me.proton.Pass`. Proton VPN is `pacman -S proton-vpn-gtk-app`. Drive has no official Linux GUI or Flathub id; bundling the CLI inside Flatpak needs a Flathub review and a Bun/SDK build that is not in this release.
