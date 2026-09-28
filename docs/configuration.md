# Configuration

| Variable / setting | Purpose |
| --- | --- |
| `PROTON_DRIVE_BIN` | Official CLI path (overrides Settings) |
| Settings → Theme | Dark, Light, or System (`Adw.StyleManager`) |
| Settings → Language | System default, English, Русский, 简体中文, العربية, Italiano, Português, Español, 한국어, 日本語; changing language restarts the Gio app. Portuguese is gettext `pt`. Arabic is RTL |
| Settings → Download folder | Local folder for toolbar CLI downloads |
| Settings → Always-on folder | User-chosen local copy of `/my-files` (skip/merge download + upload) |
| Settings → Enable always-on folder | Starts the niced CLI worker now and turns on session autostart |
| Settings → Worker / Last successful pass / Files last pass / Last error | Live activity from this app's worker lock and `sync-status.json` (official CLI has no Activity log) |
| Settings → CLI path | File picker for the `proton-drive` binary |
| Settings → CLI version / CLI updates | Live `proton-drive version` (current CLI vs whether Proton reports a newer one) |
| Settings → Start with this session | `~/.config/autostart/io.github.voxhash.ProtonDriveLinux.desktop` |
| `~/.config/proton-drive-linux/gui.json` | Saved GUI settings |
| `~/.config/proton-drive-linux/sync-status.json` | Last sync pass written by the worker (`state`, `last_success`, `last_error`, `last_pull`, `last_push`, `pid`) |
| `~/.config/proton-drive-linux/sync.lock` | Held while a niced worker pass is running |

Official CLI 0.8.0 cannot FUSE-mount Drive. The always-on folder is a local directory, not a mount.
