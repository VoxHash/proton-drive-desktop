# Usage

Launch `proton-drive-linux`. Sidebar sections map to CLI paths `/my-files`, `/photos`, `/shared-with-me`, `/trash`. Enter opens a folder. Download writes to the folder in Settings (default `~/Downloads`).

**Share** (toolbar) runs live `proton-drive sharing` on the selected file or folder: invite by email (viewer / editor / admin), list members and pending invites, create or remove a public link, stop sharing, or leave a share that was shared with you.

**Rename**, **Copy**, and **Move** (toolbar and right-click) run `proton-drive filesystem rename|copy|move`. Copy and Move open a folder picker over live `filesystem list`. F2 also renames. In **Trash**, Restore is the trash toolbar button; **Empty trash** asks for confirmation then runs `filesystem empty-trash` (permanently deletes `/trash` only, not Photos trash).

Pending invitations from `proton-drive invitation list` appear at the top of **Shared with me**. Open one to Accept or Reject (`invitation accept` / `invitation reject`).

Settings can enable an **always-on folder** (default `~/Proton Drive`). That is not a FUSE mount: official CLI 0.8.0 has no `mount` command. Enabling it starts a separate niced process (`filesystem download` then `filesystem upload` with skip/merge) and turns on session autostart so the worker stays on after login. Existing local and remote files are never replaced. Sync does not touch `/trash`.

The primary menu (hamburger) matches official Drive’s Help / Settings / About / account actions:

- **Settings** — live account email, CLI version and path, theme, download folder, always-on folder, autostart, sign out (`proton-drive auth logout`)
- **Proton Drive Help** — https://proton.me/support/drive
- **Drive CLI Help** — https://proton.me/support/drive-cli
- **Open Drive in browser** — https://drive.proton.me
- **Open always-on folder** — opens the local always-on folder
- **About** — this unofficial GUI, plus Proton Terms and Privacy links from the Windows Drive About pane
