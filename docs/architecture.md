# Architecture

GTK4 window → background thread → official `proton-drive` JSON CLI → OS keyring session.

No Proton API is reimplemented. When Proton ships a Linux Drive app, this GUI should be retired.
