# Security

Report vulnerabilities to contact@voxhash.dev. Do not file public issues for session-token leaks, account credentials, or decrypted file contents. Prefer a minimal synthetic reproduction without personal paths or names.

Only the latest published release is expected to receive security fixes during early development.

## Trust model (summary)

This project is an unofficial MIT-licensed GTK4 / libadwaita GUI. It shells out to Proton’s official `proton-drive` binary and does **not** reimplement Proton’s crypto, SRP login, or Drive API. Session material stays where the official CLI already puts it (typically GNOME Keyring / Secret Service via libsecret). This process does not operate a backend, relay, analytics service, or account database.

See also [docs/architecture.md](docs/architecture.md) for process layout and [docs/faq.md](docs/faq.md) for short answers.

## No Proton account password in this process

| Guarantee | What this app does |
| --- | --- |
| No account-password UI | Sign-in is delegated to `proton-drive auth login` (Proton’s browser flow). The GUI has no field that collects the Proton account password or mailbox key passphrase. |
| No credential store of our own | We do not write Proton passwords, recovery phrases, or session tokens into `gui.json`, logs, or a project-specific vault. The CLI owns the keyring session. |
| Argument-vector CLI only | Subprocess calls use an argv list (`subprocess.run` / `Popen`), not a shell string (`shell=True` is not used). |
| Optional public-link password is not the account password | Sharing → set public URL may pass an optional **link** password to `proton-drive sharing set-url --password …`. That protects the share URL only; it is not the Proton login password and is not persisted by this GUI. |

If you need to authenticate, run `proton-drive auth login` (or the in-app path that launches the same command) and complete the browser flow until the CLI reports success.

## Threat model

### In scope (what we try to get right)

- **Boundary:** User → GTK GUI / sync worker → local official `proton-drive` → Proton Drive; session via the OS secret store as managed by the CLI.
- **Privileged dependency:** The on-disk `proton-drive` binary. Before first Settings / first sync use, this app may verify it against Proton’s published SHA-512 digests from [proton.me/download/drive/cli](https://proton.me/download/drive/cli/index.html) and **warn** on mismatch; it does not auto-download or replace the binary.
- **Local config we write:** `~/.config/proton-drive-desktop/` (`gui.json`, sync status/lock/delta, optional verify cache). Paths and preferences only — not Proton passwords.
- **Always-on worker:** A separate niced `python3 -m proton_drive_desktop.sync` process that also shells out to the same CLI. Desktop notifications use `notify-send` for worker failure / auth-expired hints; they carry short status text, not credentials.
- **Transfer control:** In-memory transfer queue with one active CLI process; cancel targets the owned process tree only.

### Out of scope / explicit non-goals

- Reimplementing end-to-end encryption, key management, or a second Proton client protocol.
- Protecting a compromised endpoint (malware, keyloggers, a world-writable fake `proton-drive` on `PATH`, unlocked keyring, rootkits). Full-disk encryption, screen lock, OS updates, and Proton 2FA remain user controls.
- Guaranteeing Proton AG’s server-side or CLI security model (see Proton’s own Drive security / threat-model material).
- Shipping or redistributing Proton’s prebuilt CLI binaries from this repository.
- Telemetry, crash uploaders, or phones-home HTTP APIs operated by this project. The only network use from this codebase’s verify helper is fetching Proton’s public CLI index/checksums for optional SHA-512 checks; Drive traffic goes through the official CLI.

### Assets

| Asset | Who holds it |
| --- | --- |
| Proton account password / SRP material | Never held by this GUI; browser + official CLI during login |
| Session / unlock material | Official CLI + OS keyring |
| Decrypted names and file bytes on disk | User’s machine while listed, downloaded, uploaded, or synced |
| Public share link password (optional) | Passed once to the CLI for `sharing set-url`; not stored by this app |
| GUI preferences and sync fingerprints | Local config under `~/.config/proton-drive-desktop/` |

### Trust boundaries

1. **Untrusted:** Remote node names, CLI JSON stdout, filesystem events, notification text, and any binary that is not the expected official CLI.
2. **Trusted dependency:** Official `proton-drive` installed by the user (PATH, Settings → CLI path, `PROTON_DRIVE_BIN`, or `~/.local/bin/proton-drive`), preferably checksum-verified.
3. **This process:** Renders UI, builds argv, manages the sync worker and transfer queue. It can read whatever the CLI returns and whatever the user downloads into the always-on or download folders.

### Residual risks (honest limits)

- A malicious or substituted `proton-drive` binary defeats the model; treat SHA-512 warnings seriously.
- Optional share-link passwords appear on the CLI argv for that invocation (same as invoking the CLI by hand).
- Always-on sync and downloads leave plaintext copies under user-chosen local paths.
- `notify-send` and systemd user units inherit the user’s session; they are not a sandbox.

## Related docs

- [Architecture](docs/architecture.md) — process graph, sync worker, verify helper
- [Configuration](docs/configuration.md) — what is stored under `~/.config/proton-drive-desktop/`
- [FAQ](docs/faq.md) — short “does it store my password?” answer
- [Installation](docs/installation.md) — install official CLI, then this GUI
