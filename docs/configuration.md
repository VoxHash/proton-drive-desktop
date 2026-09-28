# Configuration

| Variable / setting | Purpose |
| --- | --- |
| `PROTON_DRIVE_BIN` | Official CLI path (overrides Settings) |
| Settings → Theme | Dark, Light, or System (`Adw.StyleManager`) |
| Settings → Download folder | Local folder for toolbar CLI downloads |
| Settings → Always-on folder | User-chosen local copy of `/my-files` (skip/merge download + upload) |
| Settings → Enable always-on folder | Starts the niced CLI worker now and turns on session autostart |
| Settings → CLI path | File picker for the `proton-drive` binary |
| Settings → Start with this session | `~/.config/autostart/io.github.voxhash.ProtonDriveLinux.desktop` |
| `~/.config/proton-drive-linux/gui.json` | Saved GUI settings |
| `~/.config/proton-drive-linux/sync-status.json` | Last sync pass written by the worker |

Official CLI 0.8.0 cannot FUSE-mount Drive. The always-on folder is a local directory, not a mount.
