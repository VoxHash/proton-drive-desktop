# API

Python wrapper: `proton_drive_linux.cli.ProtonDriveCli`.

```python
from proton_drive_linux.cli import ProtonDriveCli
cli = ProtonDriveCli()
print([n["name"] for n in cli.list("/my-files")])
```
