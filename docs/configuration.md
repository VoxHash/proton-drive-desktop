# Configuration

| Variable / setting | Purpose |
| --- | --- |
| `PROTON_DRIVE_BIN` | Official CLI path (overrides Settings) |
| Settings → Theme | Dark, Light, or System (`Adw.StyleManager`) |
| Settings → Download folder | Local folder for toolbar CLI downloads |
| Settings → My files folder | Always-on local copy of `/my-files` (skip/merge download + upload) |
| Settings → Keep a local My files folder | Enables the separate niced sync process |
| Settings → CLI path | File picker for the `proton-drive` binary |
| Settings → Start with this session | `~/.config/autostart/io.github.voxhash.ProtonDriveLinux.desktop` |
| `~/.config/proton-drive-linux/gui.json` | Saved GUI settings |
| `~/.config/proton-drive-linux/sync-status.json` | Last sync pass written by the worker |

Official CLI 0.8.0 cannot FUSE-mount Drive. The My files folder is a local directory, not a mount.
