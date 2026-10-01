#!/usr/bin/env python3
"""Run packaging smoke + offline unit tests (no Proton API / CLI auth).

Runs each ``tests/test_*.py`` in a subprocess with ``PROTON_DRIVE_OFFLINE=1``
so gettext / config state cannot leak across modules. Live API checks and
local ``proton-drive`` binary probes are skipped by those modules when the
flag is set (see ``tests/test_cli.py`` and ``tests/test_sync.py``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"


def main() -> int:
    paths = sorted(TESTS_DIR.glob("test_*.py"))
    if not paths:
        print("no tests/test_*.py found", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["PROTON_DRIVE_OFFLINE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    # Prefer a predictable C locale for string asserts in offline unit tests.
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")

    failed = 0
    for path in paths:
        rel = path.relative_to(ROOT)
        print(f"==> {rel}", flush=True)
        proc = subprocess.run(
            [sys.executable, "-u", str(path)],
            cwd=str(ROOT),
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            failed += 1
            print(f"FAIL {rel} (exit {proc.returncode})", file=sys.stderr, flush=True)
        else:
            print(f"ok   {rel}", flush=True)

    print(f"offline test files: {len(paths) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
