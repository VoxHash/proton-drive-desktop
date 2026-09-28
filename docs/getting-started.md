# Getting started

Install Proton Drive CLI 0.8 from https://proton.me/download/drive/cli then sign in:

```bash
proton-drive auth login
python3 tests/test_cli.py
make user-install
proton-drive-linux
```

Help in the app opens https://proton.me/support/drive. Settings reads the live CLI session (account email, CLI path, version vs Proton newer check) and can keep an always-on folder without FUSE. That Settings group shows live worker activity from this app's niced sync process. If Proton reports a newer CLI, Settings and About link to https://proton.me/download/drive/cli and https://proton.me/support/drive-cli. Settings → Language is System default or English; changing it restarts the app so GNU gettext reloads.
