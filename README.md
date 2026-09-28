# Proton Drive Linux

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CLI](https://img.shields.io/badge/proton--drive-0.8.0-6d4aff.svg)](https://proton.me/download/drive/cli/index.html)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](#installation)

Unofficial GTK4 / libadwaita desktop GUI for **Proton’s official Drive CLI**. Proton has no Linux Drive GUI yet. This app matches Drive’s My files / Photos / Shared / Trash layout and talks only to `proton-drive` already signed in on the system.

Not affiliated with Proton AG. The app/tray icon is Proton’s official Drive mark from [ProtonDriveApps/android-drive](https://github.com/ProtonDriveApps/android-drive) (GPL-3.0-or-later).

## Features

- Live listing of My files, Photos, Shared with me, and Trash
- Share and invitations from the UI (`proton-drive sharing` / `invitation list`)
- Upload, download, new folder, rename, copy, move, trash, restore, empty trash
- Help and Settings (official Drive Help URL, live CLI account, theme, download folder, always-on folder, CLI path, autostart)
- Always-on folder (official CLI 0.8.0 cannot FUSE-mount; skip/merge download/upload worker starts on enable and with this session)
- System tray on KDE/Ayatana: close hides, Quit from the tray exits
- Uses the official CLI session in GNOME Keyring / Secret Service
- Proton dark theme (`#6d4aff` / `#16141c`)

## Quick start

```bash
proton-drive version
python3 tests/test_cli.py
python3 tests/test_packaging.py
python3 tests/test_sync.py
make user-install
proton-drive-linux
```

## Installation

This is a Python GTK wrapper. It does **not** ship Proton’s CLI binary. Install the official CLI first, then this GUI.

**1. Official CLI** (required), from [proton.me/download/drive/cli](https://proton.me/download/drive/cli/index.html) or AUR `proton-drive-cli` / `proton-drive-cli-bin`:

```bash
chmod +x proton-drive
mv proton-drive ~/.local/bin/proton-drive
proton-drive auth login
proton-drive version
```

**2. GUI packages on Garuda/Arch** (same stack Proton VPN uses: GTK4 + Python):

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita gdk-pixbuf2 libsecret
```

**3. Install this app for the current user** (desktop file, hicolor icons, AppStream metainfo):

```bash
cd ~/Projects/proton-drive-linux
make user-install
proton-drive-linux
```

From a checkout without `make`: `python3 scripts/proton-drive-linux`.

### How this compares to Proton Pass and Proton VPN on this OS

| App | What is installed here | Install ease |
| --- | --- | --- |
| Proton Pass | Flatpak `me.proton.Pass` from Flathub | One command / Discover |
| Proton VPN | Native `proton-vpn-gtk-app` from Arch extra | `pacman -S proton-vpn-gtk-app` |
| Proton Drive | No official Linux GUI. This wrapper + official CLI | `make user-install` after CLI is on PATH |

A GitHub source Release is shippable now. It is **not** as easy as Pass (Flathub) or VPN (official Arch extra). Remaining blockers: no Flathub listing, no signed Arch extra package, the GUI is unsigned Python, and the official CLI must be installed separately (do not redistribute Proton’s prebuilt CLI in this repo). A real AUR PKGBUILD lives in `packaging/arch/PKGBUILD` and depends on the CLI as an optional AUR package.

## Usage

Open the primary menu (hamburger) for **Settings**, **Proton Drive Help**, and **About**. Browse folders with Enter or Open. Share (toolbar) invites people and manages public links via the official CLI. Pending invitations appear at the top of **Shared with me**. Rename, Copy, and Move use Adwaita dialogs and the live CLI. Empty trash is available in Trash after confirmation. Upload and download use the portal file dialogs. Settings → **Enable always-on folder** keeps a local directory in sync with `/my-files` using official CLI download/upload in a separate process (not a FUSE mount) and starts the worker now and at login. Sign-in, if needed, is `proton-drive auth login` in the browser.

## Configuration

| Variable / setting | Purpose | Default |
| --- | --- | --- |
| `PROTON_DRIVE_BIN` | Path to official CLI | `proton-drive` on PATH, Settings, or `~/.local/bin/proton-drive` |
| Settings → Theme | Dark / Light / System | Dark |
| Settings → Download folder | Where toolbar downloads are saved | `~/Downloads` |
| Settings → Always-on folder | Enable, path, and autostart the skip/merge CLI worker (not FUSE) | `~/Proton Drive`, off until enabled |
| Settings → Start with this session | XDG autostart | Off |
| `~/.config/proton-drive-linux/gui.json` | Persisted GUI settings | Created on first save |

## Examples

```bash
python3 -m proton_drive_linux.cli
python3 -m proton_drive_linux.sync --status
python3 tests/test_cli.py
python3 tests/test_packaging.py
python3 tests/test_sync.py
```

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT for this GUI. The Drive icon is GPL-3.0-or-later Proton AG artwork; see [LICENSE](LICENSE) and `data/icons/SOURCE`. Proton, Proton Drive, Proton Mail, Proton Pass, and Proton VPN are trademarks of Proton AG.
