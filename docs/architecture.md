# Architecture

GTK4 window → background thread → official `proton-drive` JSON CLI → OS keyring session.

No Proton API is reimplemented. When Proton ships a Linux Drive app, this GUI should be retired.

The window, `.desktop` file, hicolor theme, and StatusNotifierItem tray use Proton’s official Drive launcher mark from `ProtonDriveApps/android-drive`.

The always-on folder worker is a separate niced `python3 -m proton_drive_linux.sync` process. It never runs `filesystem download` on the GTK thread, and it waits while the window is listing files unless the user clicks Sync now.
