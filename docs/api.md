# API

Python wrapper: `proton_drive_linux.cli.ProtonDriveCli`.

```python
from proton_drive_linux.cli import ProtonDriveCli
cli = ProtonDriveCli()
print([n["name"] for n in cli.list("/my-files")])
print(cli.invitation_list())
print(cli.sharing_status("/my-files/Business"))
cli.rename("/my-files/old", "new")
cli.copy("/my-files/new", "/my-files", name="new-copy")
cli.move("/my-files/new-copy", "/my-files/Business")
# cli.empty_trash()  # permanently deletes every item in /trash
```

My files folder worker (separate process, not FUSE):

```python
from proton_drive_linux.sync import format_status_line, run_once
print(format_status_line())
# run_once(force=True)  # pulls /my-files into the configured folder
```
