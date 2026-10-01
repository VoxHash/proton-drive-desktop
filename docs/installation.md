# Installation

Dependencies: GTK 4, libadwaita, Python 3.12+, official `proton-drive` CLI 0.8.0, libsecret.

## One-shot installer

```bash
./install.sh              # system GTK deps, make user-install, download CLI if missing
./install.sh --skip-cli   # GUI only (you install proton-drive yourself)
./install.sh --with-cli   # re-download CLI; verify SHA-512 before install
./install.sh --yes        # non-interactive package manager flags where supported
```

Optional CLI download uses Proton’s published index
https://proton.me/download/drive/cli/index.html (same source as `proton_drive_desktop/cli_verify.py`).
On SHA-512 mismatch the script exits and does not install the binary.

## Distro packages (manual)

On Garuda/Arch:

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita gdk-pixbuf2 libsecret
```

Debian/Ubuntu-style (manual deps for source / `install.sh`):

```bash
sudo apt-get install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  libgtk-4-1 libadwaita-1-0 libsecret-1-0 gettext
```

## Debian / Ubuntu `.deb`

GitHub Releases may include `proton-drive-desktop_<version>_all.deb` (Architecture: all). It installs **this GTK GUI only** under `/usr` and Depends on distro GTK4 / libadwaita / PyGObject packages. It does **not** ship the official `proton-drive` CLI — install that separately and keep it on `PATH`.

```bash
# download .deb + SHA256SUMS from the release, then:
sha256sum -c SHA256SUMS
sudo dpkg -i proton-drive-desktop_<version>_all.deb
# if dpkg reports missing Depends:
sudo apt-get install -f
proton-drive-desktop
```

Build locally (needs `make`, `msgfmt`, `tar`, `gzip`, `ar`; uses `dpkg-deb` when available):

```bash
make deb
# → dist/proton-drive-desktop_<version>_all.deb
```

Uninstall the system package (leaves user config and the official CLI alone):

```bash
sudo dpkg -r proton-drive-desktop
```

User installs via `./install.sh` / `make user-install` are unchanged and still uninstall with `make user-uninstall` or `./install.sh --uninstall` (not `dpkg -r`).

## Official CLI (not bundled)

```bash
# from https://proton.me/download/drive/cli  or AUR proton-drive-cli / proton-drive-cli-bin
proton-drive auth login
proton-drive version
```

Or let `./install.sh` download it after checksum verification into `~/.local/bin/proton-drive`.

## Install this GUI

User install (desktop file, hicolor icons, AppStream metainfo):

```bash
cd ~/Projects/proton-drive-desktop
make user-install
proton-drive-desktop
```

`make user-install` places:

| Path | What |
| --- | --- |
| `~/.local/bin/proton-drive-desktop` | Launcher script |
| `~/.local/lib/proton-drive-desktop/` | Python package |
| `~/.local/share/applications/io.github.voxhash.ProtonDriveDesktop.desktop` | Applications menu entry (`Name=Proton Drive`) |
| `~/.local/share/metainfo/io.github.voxhash.ProtonDriveDesktop.metainfo.xml` | AppStream metainfo |
| `~/.local/share/icons/hicolor/.../io.github.voxhash.ProtonDriveDesktop.*` | Icons |
| `~/.local/share/locale/*/LC_MESSAGES/proton-drive-desktop.mo` | gettext catalogs |

It rewrites `Exec=` / `TryExec=` in the installed `.desktop` file to the absolute `~/.local/bin/proton-drive-desktop` path (so menus that check `TryExec` without `~/.local/bin` on `PATH` still show **Proton Drive**), then runs `update-desktop-database` and `gtk-update-icon-cache` when available.

System-wide:

```bash
sudo make PREFIX=/usr/local install
```

Arch packaging (AUR-ready, not published): `packaging/arch/PKGBUILD`. It installs the GUI only; install the CLI from AUR or Proton’s download page.

## Uninstall

Remove what `make user-install` / `./install.sh` put under `~/.local` (and optional session helpers):

```bash
make user-uninstall
# or:
./scripts/uninstall.sh
./install.sh --uninstall
```

That removes the GUI binary, lib tree, desktop entry, metainfo, hicolor icons, locale `.mo` files, XDG autostart (`~/.config/autostart/io.github.voxhash.ProtonDriveDesktop.desktop` if Settings created it), and optional systemd user sync units (`proton-drive-desktop-sync.{service,timer,path}`).

Defaults (safe for shared CLI installs):

- Does **not** delete `~/.local/bin/proton-drive` (official Proton CLI). Use `--remove-cli` only if you want that binary gone too.
- Does **not** wipe `~/.config/proton-drive-desktop` (settings / sync state). Use `--purge` to delete it.

```bash
./scripts/uninstall.sh --purge
./install.sh --uninstall --purge --remove-cli
```

System-wide installs: `sudo make PREFIX=/usr/local uninstall` (does not touch XDG autostart or systemd user units under your home).

Debian package installs: `sudo dpkg -r proton-drive-desktop` (does not delete `~/.config/proton-drive-desktop` or `~/.local/bin/proton-drive`).

## GitHub Releases

Pushing a `v*` tag runs `.github/workflows/release.yml`, which:

1. Builds `dist/proton-drive-desktop-<version>.tar.gz` via `scripts/build-source-tarball.sh`
2. Writes `dist/SHA256SUMS` (SHA-256 of release assets)
3. Optionally builds an AppImage (`packaging/appimage/build-appimage.sh`) and attaches it when that step succeeds
4. Optionally builds a Debian `.deb` (`packaging/debian/build-deb.sh`) and attaches it when that step succeeds
5. Creates or updates the GitHub Release with those assets

Locally:

```bash
make dist                 # source tarball + SHA256SUMS
make deb                  # optional .deb + SHA256SUMS entry
sha256sum -c dist/SHA256SUMS
```

## Optional AppImage

```bash
make appimage
# → dist/ProtonDriveDesktop-<version>-<arch>.AppImage
```

Requirements to **build**: `make`, `python3`, `curl`, `gettext` (`msgfmt`). The script downloads `appimagetool` into `dist/.tools/` when missing (needs network; FUSE not required — uses `--appimage-extract-and-run`).

Requirements to **run**: host `python3` with PyGObject, GTK 4, libadwaita, and a system `proton-drive` on `PATH`. The AppImage bundles this GUI only and refuses to package if a `proton-drive` binary appears under the AppDir.

## Verify after install

```bash
make test-offline
```

This is not a Flatpak. Proton Pass on this machine is `flatpak install flathub me.proton.Pass`. Proton VPN is `pacman -S proton-vpn-gtk-app`. Drive has no official Linux GUI or Flathub id; bundling the CLI inside Flatpak needs a Flathub review and a Bun/SDK build that is not in this release.
