# API

Python wrapper: `proton_drive_linux.cli.ProtonDriveCli`.

```python
from proton_drive_linux.cli import ProtonDriveCli
cli = ProtonDriveCli()
print(cli.version_info())
print([n["name"] for n in cli.list("/my-files")])
print(cli.invitation_list())
print(cli.sharing_status("/my-files/Business"))
cli.rename("/my-files/old", "new")
cli.copy("/my-files/new", "/my-files", name="new-copy")
cli.move("/my-files/new-copy", "/my-files/Business")
cli.album_create("Trip")
cli.album_add_photo("/albums/Trip", ["/photos/PHOTO-UID"])
cli.album_update("/albums/Trip", name="Summer")
cli.album_remove_photo("/albums/Summer", ["/photos/PHOTO-UID"])
# cli.album_delete("/albums/Summer", save=True)
# cli.delete("/trash/pdl-del-sample")  # one already-trashed item
# cli.empty_trash()  # permanently deletes every item in /trash
```

Always-on folder worker (separate process, not FUSE):

```python
from proton_drive_linux.sync import activity_snapshot, format_status_line, run_once
print(activity_snapshot())
print(format_status_line())
# python3 -m proton_drive_linux.sync --status  # same JSON Settings reads
# run_once(force=True)  # pulls /my-files into the configured folder
```
