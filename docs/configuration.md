# Configuration

| Variable / setting | Purpose |
| --- | --- |
| `PROTON_DRIVE_BIN` | Official CLI path (overrides Settings) |
| Settings → Theme | Dark, Light, or System (`Adw.StyleManager`) |
| Settings → Language | System default, English, Русский, 简体中文, العربية, Italiano, Português, Español, 한국어, 日本語; changing language restarts the Gio app. Portuguese is gettext `pt`. Arabic is RTL |
| Settings → Download folder | Local folder for toolbar CLI downloads |
| Settings → Always-on folder | One or more local folders synced with `/my-files/...` (download + upload; default skip/merge). Legacy single-folder installs migrate into the first `sync_pairs` entry |
| Settings → Sync pairs | Add/remove/edit extra local↔remote pairs (`gui.json` `sync_pairs`); each has `id`, `enabled`, `local_path`, `remote_root`, optional `exclude` / `conflict_policy` / `direction` |
| Settings → Pause sync | Keep always-on enabled but skip worker passes until resume (also on the tray menu) |
| Settings → Sync direction | Always-on pass half(s): bidirectional (default), upload-only, or download-only (`gui.json` `sync_direction`; also per-pair) |
| Settings → Conflict policy | Always-on CLI `-f`/`-d`: skip existing files (default) or rename conflicting files; folders always merge |
| Settings → Enable always-on folder | Starts the niced CLI worker now and turns on session autostart |
| Settings → Worker / Last successful pass / Files last pass / Recent passes / Last error | Live activity from this app's worker lock and `sync-status.json` (bounded `history` of last passes; official CLI has no Activity log) |
| Settings → Guided setup | Short Adw welcome flow: CLI SHA-512 verify, preview, seed/assume-synced, enable always-on (`gui.json` `setup_completed`) |
| Settings → Storage quota | Probes live `proton-drive --help` for an account/storage quota command; CLI 0.8.0 has none → Unavailable (no invented numbers) |
| Settings → CLI path | File picker for the `proton-drive` binary |
| Settings → CLI version / CLI updates | Live `proton-drive version` (current CLI vs whether Proton reports a newer one) |
| Settings → Start with this session | `~/.config/autostart/io.github.voxhash.ProtonDriveDesktop.desktop` |
| Settings → Sync interval (seconds) | Always-on poll interval in `gui.json` (`sync_interval_seconds`; default 300; range 60–86400). Drives GUI due-checks and systemd `OnUnitActiveSec` |
| Settings → Per-pass timeout | Optional watchdog in `gui.json` (`sync_pass_timeout_seconds`; `0` = off, else 60–86400; suggested 3600). Cancels the owned CLI transfer process tree when a pass exceeds the budget |
| Settings → systemd user timer | Optional `~/.config/systemd/user/proton-drive-desktop-sync.{service,timer}` via `systemctl --user` (interval from Sync interval; alongside XDG, not a replacement) |
| Settings → Sync soon after local edits | Optional path trigger (`gui.json` `sync_path_trigger`): debounced recursive Gio/inotify while the app runs; optional `proton-drive-desktop-sync.path` for the folder root and immediate subfolders via `systemctl --user` (systemd cannot watch deeply nested paths; deep edits while the GUI is closed wait for the sync interval; path unit is rewritten when the always-on folder changes) |
| Settings → Assume already synced | Seeds `sync-delta.json` from a real Drive list + local fingerprints so the next pass skips bulk transfer when both sides already match (also offered on first enable preview) |
| `~/.config/proton-drive-desktop/gui.json` | Saved GUI settings (`sync_pairs`, `sync_paused`, `setup_completed`, legacy `sync_folder` / `sync_remote_root` mirrored from the primary pair) |
| `~/.config/proton-drive-desktop/sync-status.json` | Last sync pass + bounded Activity `history` written by the worker (`state`, `last_success`, `last_error`, `last_pull`, `last_push`, skips, timeout, `pid`) |
| `~/.config/proton-drive-desktop/sync-delta.json` | Per-pair local delta fingerprints (`version` 2 store with `pairs.<id>`); legacy single-pair files migrate on load |
| `~/.config/proton-drive-desktop/sync.lock` | Held while a niced worker pass is running |

Official CLI 0.8.0 cannot FUSE-mount Drive. Always-on sync uses real local directories, not a mount.
