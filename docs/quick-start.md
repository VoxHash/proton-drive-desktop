# Quick start

```bash
cd ~/Projects/proton-drive-desktop
./install.sh --skip-cli   # or ./install.sh to also fetch CLI after SHA-512 verify
python3 tests/test_cli.py
python3 tests/test_packaging.py
python3 tests/test_sync.py
python3 tests/test_sync_pairs.py
python3 tests/test_i18n.py
proton-drive-desktop
```

First run shows Guided setup (verify CLI → preview → optional assume-synced → enable always-on). Skip is fine; reopen from the app menu later.
