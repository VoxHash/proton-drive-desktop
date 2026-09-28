# Proton Drive Linux

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CLI](https://img.shields.io/badge/proton--drive-0.8.0-6d4aff.svg)](https://proton.me/download/drive/cli/index.html)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](#installation)

Unofficial GTK4 / libadwaita desktop GUI for **Proton’s official Drive CLI**. Proton has no Linux Drive GUI yet; Mail and Pass on this machine are Electron apps. This app matches that Drive layout (My files, Shared with me, Trash) and talks only to `proton-drive` already signed in on the system.

Not affiliated with Proton AG.

## Features

- Live listing of My files, Shared with me, and Trash
- Upload, download, new folder, trash, restore
- Uses the official CLI session in GNOME Keyring / Secret Service
- Proton dark theme (`#6d4aff` / `#16141c`)

## Quick start

```bash
proton-drive version
python3 tests/test_cli.py
proton-drive-linux
```

## Installation

Official CLI must already be installed (`~/.local/bin/proton-drive`). Then:

```bash
cd ~/Projects/proton-drive-linux
ln -sfn "$PWD/scripts/proton-drive-linux" ~/.local/bin/proton-drive-linux
install -Dm644 data/io.github.voxhash.ProtonDriveLinux.desktop ~/.local/share/applications/
proton-drive-linux
```

## Usage

Browse folders with Enter or the Open button. Upload and download use the portal file dialogs. Sign-in, if needed, is `proton-drive auth login` in the browser.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `PROTON_DRIVE_BIN` | Path to official CLI | `proton-drive` on PATH or `~/.local/bin/proton-drive` |

## Examples

```bash
python3 -m proton_drive_linux.cli
python3 tests/test_cli.py
```

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. Proton, Proton Drive, Proton Mail, and Proton Pass are trademarks of Proton AG.
