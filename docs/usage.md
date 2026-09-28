# Usage

Launch `proton-drive-linux`. Sidebar sections map to CLI paths `/my-files`, `/photos`, `/shared-with-me`, `/trash`. Enter opens a folder. Download writes to the folder in Settings (default `~/Downloads`).

**Photos** lists albums from `proton-drive album list` above the capture-date timeline. New album (the folder-new toolbar button in Photos) runs `album create`. Rename an album with the toolbar, F2, or right-click (`album update -n`). Delete album asks for confirmation then runs `album delete -s` (photos stay in the timeline). Open a day, select a photo, then Copy / Add to album (`album add-photo` with `/photos/{uid}`). Inside an album, Remove from album or the trash button runs `album remove-photo`.

**Share** (toolbar) runs live `proton-drive sharing` on the selected file or folder: invite by email (viewer / editor / admin), list members and pending invites, create or remove a public link, stop sharing, or leave a share that was shared with you.

**Rename**, **Copy**, and **Move** (toolbar and right-click) run `proton-drive filesystem rename|copy|move`. Copy and Move open a folder picker over live `filesystem list`. F2 also renames. In **Trash**, Restore is the trash toolbar button. **Delete permanently** asks for confirmation then runs `filesystem delete` on the selected trashed item only. **Empty trash** asks for confirmation then runs `filesystem empty-trash` (permanently deletes `/trash` only, not Photos trash).

Pending invitations from `proton-drive invitation list` appear at the top of **Shared with me**. Open one to Accept or Reject (`invitation accept` / `invitation reject`).

Settings can enable an **always-on folder** (default `~/Proton Drive`). That is not a FUSE mount: official CLI 0.8.0 has no `mount` command. Enabling it starts a separate niced process (`filesystem download` then `filesystem upload` with skip/merge) and turns on session autostart so the worker stays on after login. Existing local and remote files are never replaced. Sync does not touch `/trash`. Settings shows live **Worker** (Off / Stopped / Running with pid), **Last successful pass**, **Files last pass**, and **Last error** from `~/.config/proton-drive-linux/sync-status.json` and the worker lock. Official `proton-drive` has no Windows-style Activity log.

The primary menu (hamburger) matches official Drive’s Help / Settings / About / account actions:

- **Settings** — live account email, CLI version vs Proton newer check and path, theme, language (System default, English, ru, zh_CN, ar, it, pt, es, ko, ja; restarts the app; Arabic RTL), download folder, always-on folder (enable, path, worker activity), autostart, sign out (`proton-drive auth logout`)
- **Proton Drive Help** — https://proton.me/support/drive
- **Drive CLI Help** — https://proton.me/support/drive-cli
- **Open Drive in browser** — https://drive.proton.me
- **Open always-on folder** — opens the local always-on folder
- **About** — this unofficial GUI, live `proton-drive version` (latest vs newer), plus Proton Terms and Privacy links from the Windows Drive About pane
