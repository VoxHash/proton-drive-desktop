# Roadmap

- [x] GTK4 GUI over official CLI
- [x] My files / Shared with me / Trash
- [x] Upload, download, mkdir, trash
- [x] System tray (StatusNotifierItem)
- [x] Photos timeline
- [x] Help and Settings (official Drive Help, live CLI account/config)
- [x] Official Proton Drive app and tray icon
- [x] Desktop + AppStream + `make user-install` / Arch PKGBUILD
- [x] Sharing invites from the UI (`proton-drive sharing` / `invitation`)
- [x] Rename, copy, move, empty trash in the UI (CLI already has these)
- [x] Always-on local folder in Settings (enable, path, autostart the niced CLI worker; official CLI 0.8.0 has no FUSE `mount`)
- [ ] AUR publish and Flathub listing
- [ ] Replace with Proton's official Linux GUI when they ship it

True FUSE is not available from Proton Drive CLI 0.8.0: live `proton-drive --help` and [ProtonDriveApps/sdk](https://github.com/ProtonDriveApps/sdk) list auth, filesystem, sharing, invitation, album, and photo commands only. rclone `protondrive` and unofficial FUSE clients are out of scope. The shipped path is a user-chosen always-on folder, not a fake mount.
