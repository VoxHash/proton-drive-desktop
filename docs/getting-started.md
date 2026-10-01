# Getting started

One-shot (GTK deps, desktop launcher, optional CLI with Proton SHA-512 verify):

```bash
./install.sh
proton-drive auth login
proton-drive-desktop
```

Or install the CLI from https://proton.me/download/drive/cli yourself, then:

```bash
proton-drive auth login
python3 tests/test_cli.py
make user-install
proton-drive-desktop
```

On first launch, a short Guided setup dialog offers CLI checksum verify, always-on preview, assume-already-synced (seed), and enable always-on. You can reopen it anytime from the app menu (Guided setup) or Settings → Always-on folder. Help in the app opens https://proton.me/support/drive. Settings reads the live CLI session (account email, CLI path, version vs Proton newer check) and can keep one or more always-on folder pairs without FUSE. That Settings group shows live worker activity and recent pass history from this app's niced sync process. Pause sync from Settings or the tray without turning always-on off. If Proton reports a newer CLI, Settings and About link to https://proton.me/download/drive/cli and https://proton.me/support/drive-cli. Settings → Language is System default, English, or ru / zh_CN / ar / it / pt / es / ko / ja (native names; Arabic RTL); changing it restarts the app so GNU gettext reloads.
