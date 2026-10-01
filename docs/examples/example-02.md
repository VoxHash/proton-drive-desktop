# Example: install, Guided setup, multi-folder sync, pause, Activity

## Install and launch

One-shot (deps + user-install; optional CLI with SHA-512 verify):

```bash
./install.sh
proton-drive-desktop
```

From a [GitHub Release](https://github.com/VoxHash/proton-drive-desktop/releases) source tarball:

```bash
tar -xzf proton-drive-desktop-*.tar.gz
cd proton-drive-desktop-*
sha256sum -c SHA256SUMS   # if you also downloaded SHA256SUMS
./install.sh
proton-drive-desktop
```

GUI only (CLI already on `PATH`):

```bash
make user-install
proton-drive-desktop
```

From the repo without installing:

```bash
python3 scripts/proton-drive-desktop
```

## Guided setup (first launch)

On first run the app presents a short Adw welcome flow (also: primary menu → **Guided setup**, or Settings → Always-on → **Guided setup** → Open):

1. **CLI checksum** — compares the on-disk `proton-drive` binary to Proton’s published SHA-512 (warn only; does not replace the binary).
2. **Preview** — dry-run style counts of what the first always-on pass would pull/push (no destructive deletes).
3. **Assume already synced (seed)** — optional: record current local + remote fingerprints so the next pass skips bulk transfer when both sides already match.
4. **Enable always-on** — starts the niced worker and session autostart.

`gui.json` gets `setup_completed` when you finish or dismiss the flow.

## Multi-folder sync pairs

Settings → Always-on folder → **Sync pairs**:

1. Enable always-on (or finish Guided setup).
2. **Add** a pair: choose a local directory and a remote root under `/my-files/...` (not only the whole tree).
3. Optionally set per-pair exclude globs, conflict policy, and direction (bidirectional / upload-only / download-only).
4. **Edit** or **Remove** pairs as needed. A legacy single-folder install migrates into the first `sync_pairs` entry automatically.

Config keys live in `~/.config/proton-drive-desktop/gui.json` under `sync_pairs`. See [Configuration](../configuration.md).

## Pause / resume

- **Settings** → **Pause sync** — keeps always-on enabled but skips worker passes until you turn pause off.
- **Tray** → **Pause sync** / **Resume sync** — same flag (`gui.json` `sync_paused`).

While paused, Activity shows Worker as paused; Sync now / resume clears the flag and can schedule a pass.

## Activity history

Settings → Always-on group shows live **Worker**, **Last successful pass**, **Files last pass**, **Last error**, and a bounded **Recent passes** list (pull / push / skip / error / timeout notes) from `~/.config/proton-drive-desktop/sync-status.json`. Official `proton-drive` has no Windows-style Activity log — this history is from this app’s niced worker only.

```bash
python3 -m proton_drive_desktop.sync --status
```

## Language and theme

Settings → Language lists System default, English, and ru / zh_CN / ar / it / pt / es / ko / ja. Changing language restarts the Gio app. Arabic is RTL.

## Interop (not this app)

For FUSE / rclone / TrueNAS / Home Assistant recipes beside this GUI, see [Usage — Interop](../usage.md#interop-not-replace) and [FAQ](../faq.md). This project does not productize those niches.
