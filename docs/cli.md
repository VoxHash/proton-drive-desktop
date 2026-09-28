# CLI

This GUI does not replace Proton's CLI. It runs:

```bash
proton-drive filesystem list PATH -j
proton-drive filesystem info PATH -j
proton-drive filesystem upload LOCAL... PARENT -f skip -d merge -t
proton-drive filesystem download REMOTE FOLDER -f skip -d merge
proton-drive filesystem create-folder PARENT NAME
proton-drive filesystem trash PATH
proton-drive photo timeline -j
proton-drive album list -j
proton-drive photo download PATH FOLDER -c rename
proton-drive photo upload LOCAL... -c skip
proton-drive auth login
```
