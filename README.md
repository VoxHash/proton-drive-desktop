# Proton Drive Desktop

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/VoxHash/proton-drive-desktop?display_name=tag&sort=semver)](https://github.com/VoxHash/proton-drive-desktop/releases)
[![CLI](https://img.shields.io/badge/proton--drive-0.8.0-6d4aff.svg)](https://proton.me/download/drive/cli/index.html)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](#installation)
[![CI](https://img.shields.io/github/actions/workflow/status/VoxHash/proton-drive-desktop/ci.yml?branch=main&label=CI)](https://github.com/VoxHash/proton-drive-desktop/actions)

Unofficial GTK4 / libadwaita desktop GUI for **Proton’s official Drive CLI**. Proton has no Linux Drive GUI yet. This app matches Drive’s My files / Photos / Shared / Trash layout and talks only to `proton-drive` already signed in on the system.

Not affiliated with Proton AG. The app/tray icon is Proton’s official Drive mark from [ProtonDriveApps/android-drive](https://github.com/ProtonDriveApps/android-drive) (GPL-3.0-or-later).

## Features

- Live listing of My files, Photos, Shared with me, and Trash
- UI languages: System default, English, Russian, Simplified Chinese, Arabic (RTL), Italian, Portuguese (`pt`), Spanish, Korean, Japanese
- Photos albums: create, rename, delete, add and remove photos (`proton-drive album`)
- Share and invitations from the UI (`proton-drive sharing` / `invitation list`)
- Upload, download, new folder, rename, copy, move, trash, restore, delete permanently, empty trash
- Drag-and-drop upload onto My files (files and folders into the current remote folder)
- Help and Settings (official Drive Help URL, live CLI account, Storage quota Unavailable until Proton’s CLI exposes it, CLI version vs Proton newer check, theme, language, download folder, always-on folder, CLI path, autostart)
- Always-on folder pairs (official CLI 0.8.0 cannot FUSE-mount; multi-folder local ↔ `/my-files/...`; Guided setup; Pause / resume from Settings and tray; Activity history of recent passes)
- **Interop, not replace** — FUSE / rclone / TrueNAS / Home Assistant are documented by link only (not vendored): see [docs/usage.md](docs/usage.md#interop-not-replace)
- System tray on KDE/Ayatana: close hides, Quit from the tray exits; Pause / Resume sync when always-on is enabled
- Uses the official CLI session in GNOME Keyring / Secret Service
- Proton dark theme (`#6d4aff` / `#16141c`)

## Quick start

```bash
./install.sh            # or: make user-install  (CLI already on PATH)
proton-drive auth login
make test-offline
proton-drive-desktop
```

Walkthroughs (Guided setup, sync pairs, pause, Activity): [docs/examples/example-02.md](docs/examples/example-02.md).

## Installation

This is a Python GTK wrapper. It does **not** ship Proton’s CLI binary. The GUI talks to a system `proton-drive` on `PATH`.

### One-shot (`install.sh`)

From a git checkout or a [GitHub Release](https://github.com/VoxHash/proton-drive-desktop/releases) source tarball:

```bash
./install.sh            # GTK deps + make user-install; download CLI if missing (SHA-512 verified)
./install.sh --skip-cli # GUI only
./install.sh --with-cli # re-download CLI and verify against Proton’s published SHA-512
./install.sh --uninstall              # remove GUI user-install (keeps CLI + config)
./install.sh --uninstall --purge      # also delete ~/.config/proton-drive-desktop
./install.sh --uninstall --remove-cli # also delete ~/.local/bin/proton-drive
```

CLI downloads use Proton’s index at [proton.me/download/drive/cli](https://proton.me/download/drive/cli/index.html). A checksum mismatch aborts; the script never installs a bad binary. Uninstall defaults leave the official CLI and GUI config alone; see [docs/installation.md](docs/installation.md#uninstall).

### Manual

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
cd ~/Projects/proton-drive-desktop
make user-install
proton-drive-desktop
```

After install, the applications menu shows **Proton Drive** (`io.github.voxhash.ProtonDriveDesktop.desktop` under `~/.local/share/applications/`). Uninstall with `make user-uninstall` or `./install.sh --uninstall` (optional `--purge` / `--remove-cli`; see [docs/installation.md](docs/installation.md#uninstall)).

From a checkout without `make`: `python3 scripts/proton-drive-desktop`.

### GitHub Releases and AppImage

Tagged releases (`v*`) publish a source tarball and `SHA256SUMS` via `.github/workflows/release.yml`. Verify with `sha256sum -c SHA256SUMS`.

Optional AppImage (`make appimage` or the release asset when the CI AppImage step succeeds) bundles **this GUI only**. It still needs host `python3` / PyGObject / GTK4 / libadwaita and a system `proton-drive` on `PATH`. Proton’s CLI is never vendored inside the AppImage. Building locally downloads `appimagetool` into `dist/.tools/` when missing.

### How this compares to Proton Pass and Proton VPN on this OS

| App | What is installed here | Install ease |
| --- | --- | --- |
| Proton Pass | Flatpak `me.proton.Pass` from Flathub | One command / Discover |
| Proton VPN | Native `proton-vpn-gtk-app` from Arch extra | `pacman -S proton-vpn-gtk-app` |
| Proton Drive | No official Linux GUI. This wrapper + official CLI | `./install.sh` or `make user-install` after CLI is on PATH |

Remaining blockers vs Pass/VPN: no Flathub listing, no signed Arch extra package, the GUI is unsigned Python, and the official CLI must stay a separate install (do not redistribute Proton’s prebuilt CLI in this repo). A real AUR PKGBUILD lives in `packaging/arch/PKGBUILD` and depends on the CLI as an optional AUR package.

## Usage

Open the primary menu (hamburger) for **Settings**, **Guided setup**, **Proton Drive Help**, and **About**. Settings → **Storage quota** probes live `proton-drive --help` and shows Unavailable on CLI 0.8.0 (no public quota command; no invented numbers). **Interop** (FUSE / rclone / TrueNAS / HA): [docs/usage.md](docs/usage.md#interop-not-replace) — link-only; not part of this repo. Browse folders with Enter or Open. Share (toolbar) invites people and manages public links via the official CLI. Pending invitations appear at the top of **Shared with me**. Rename, Copy, and Move use Adwaita dialogs and the live CLI. In Photos, New album / Rename / Add to album / Remove from album / Delete album call `proton-drive album`. In Trash, Delete permanently removes one selected item (`filesystem delete`) after confirmation; Empty trash still clears all of `/trash`. Upload and download use the portal file dialogs. Settings → **Enable always-on folder** / **Sync pairs** keeps one or more local directories in sync with `/my-files/...` using official CLI download/upload in a separate process (not a FUSE mount). **Pause sync** (Settings or tray) skips passes without disabling always-on. That Settings group also shows live **Worker**, **Last successful pass**, **Files last pass**, **Recent passes** (Activity history), and **Last error** from this app's worker status file — official `proton-drive` has no Activity log. Settings → **CLI version** / **CLI updates** run live `proton-drive version`. If Proton reports a newer CLI, Download and CLI Help open https://proton.me/download/drive/cli and https://proton.me/support/drive-cli; this app does not download Proton binaries. Settings → **Language** is System default, English, Русский, 简体中文, العربية, Italiano, Português, Español, 한국어, or 日本語; changing it saves `~/.config/proton-drive-desktop/gui.json` and restarts this Gio app so gettext reloads. Arabic uses a right-to-left GTK layout. Portuguese ships as gettext `pt` (covers `pt_BR` too). Sign-in, if needed, is `proton-drive auth login` in the browser.

## Configuration

| Variable / setting | Purpose | Default |
| --- | --- | --- |
| `PROTON_DRIVE_BIN` | Path to official CLI | `proton-drive` on PATH, Settings, or `~/.local/bin/proton-drive` |
| Settings → Theme | Dark / Light / System | Dark |
| Settings → Language | System default, English, or ru / zh_CN / ar / it / pt / es / ko / ja (native names; Arabic RTL; `pt` also matches pt_BR); restarts the app | System default |
| Settings → Download folder | Where toolbar downloads are saved | `~/Downloads` |
| Settings → Storage quota | Probes live `proton-drive --help` for a quota command; Unavailable on CLI 0.8.0 (no invented numbers) | Unavailable |
| Settings → Always-on / Sync pairs | Enable, multi-folder local↔`/my-files/...` pairs, Pause sync, Guided setup, live Activity (worker + recent passes), autostart skip/merge worker (not FUSE) | `~/Proton Drive`, off until enabled |
| Settings → Sync direction | Bidirectional (default), upload-only, or download-only (`gui.json` `sync_direction`) | Bidirectional |
| Settings → CLI version / CLI updates | Live `proton-drive version` (current CLI vs whether Proton reports a newer one) | From the installed CLI |
| Settings → CLI path | File picker for the `proton-drive` binary | PATH or `~/.local/bin/proton-drive` |
| Settings → Start with this session | XDG autostart | Off |
| Settings → Sync interval (seconds) | Always-on poll interval for GUI due-checks and systemd timer (`gui.json` `sync_interval_seconds`) | 300 (60–86400) |
| Settings → Per-pass timeout | Optional watchdog budget per always-on pass; cancels the owned CLI transfer tree when exceeded (`gui.json` `sync_pass_timeout_seconds`) | Off (`0`; 60–86400 when on, suggested 3600) |
| Settings → systemd user timer | Optional `systemctl --user` oneshot service + timer for the always-on worker (alongside XDG; interval from Sync interval) | Off |
| Settings → Sync soon after local edits | Optional path trigger: recursive debounced inotify (Gio) while the app runs + optional `systemd.path` for root + immediate subfolders (`gui.json` `sync_path_trigger`; deep nested edits while closed use the sync interval) | Off |
| Settings → Assume already synced | Seed `sync-delta.json` from a real Drive list + local fingerprints so the next pass skips bulk transfer when both sides already match (also on first enable) | Manual |
| `~/.config/proton-drive-desktop/gui.json` | Persisted GUI settings | Created on first save |
| `~/.config/proton-drive-desktop/sync-status.json` | Last always-on folder pass written by the niced worker | Created on the first pass |

## Examples

```bash
python3 -m proton_drive_desktop.cli
python3 -m proton_drive_desktop.sync --status
make test-offline
```

Markdown walkthroughs: [docs/examples/example-01.md](docs/examples/example-01.md) (list My files), [docs/examples/example-02.md](docs/examples/example-02.md) (install, Guided setup, sync pairs, pause, Activity).

## Security

Threat model and “no Proton account password in this process” guarantees: [SECURITY.md](SECURITY.md). Report vulnerabilities to contact@voxhash.dev (not in public issues for session leaks).

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT for this GUI. The Drive icon is GPL-3.0-or-later Proton AG artwork; see [LICENSE](LICENSE) and `data/icons/SOURCE`. Proton, Proton Drive, Proton Mail, Proton Pass, and Proton VPN are trademarks of Proton AG.
