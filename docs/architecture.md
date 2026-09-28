# Architecture

GTK4 window → background thread → official `proton-drive` JSON CLI → OS keyring session.

No Proton API is reimplemented. When Proton ships a Linux Drive app, this GUI should be retired.

The window, `.desktop` file, hicolor theme, and StatusNotifierItem tray use Proton’s official Drive launcher mark from `ProtonDriveApps/android-drive`.

The always-on folder worker is a separate niced `python3 -m proton_drive_linux.sync` process. It never runs `filesystem download` on the GTK thread, and it waits while the window is listing files unless the user clicks Sync now. Each pass writes `~/.config/proton-drive-linux/sync-status.json` and holds `sync.lock` while running. Settings reads that file and the lock every two seconds for Worker / last pass / last error. Official `proton-drive` has no Activity log.

Settings and About parse live `proton-drive version` (Proton fetches https://proton.me/download/drive/cli/version.json itself). This GUI only displays that result and links to Proton’s CLI download page; it does not fetch or store Proton binaries.

GTK UI strings go through GNU gettext (`proton_drive_linux.i18n`, domain `proton-drive-linux`). English is the source language and the shipped catalog (`po/en.po`). Settings → Language is System default (OS locale, falling back to English) or English. Changing language writes `language` in `gui.json` and `execv`s this Gio process so catalogs reload. `make user-install` compiles and installs `en/LC_MESSAGES/proton-drive-linux.mo`. Desktop and AppStream stay English.
