"""Optional local path trigger: run an always-on pass soon after folder edits.

Uses a debounce stamp (``sync-path-request``) so GUI ``due_for_pass`` can
bypass the fixed interval. The GTK app watches the always-on tree with
``Gio.FileMonitor`` (inotify on Linux). Optional ``systemd.path`` is managed
in ``systemd_sync`` for passes when the window is not open.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import sync_path_request_path

# Quiet period after the last local edit before requesting a sync pass.
PATH_TRIGGER_DEBOUNCE_SECONDS = 15

# Cap recursive Gio monitors so huge trees do not open unbounded watches.
_MAX_MONITORS = 512


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def request_pass_soon() -> Path:
    """Mark that a sync pass should run soon (honored by ``due_for_pass``)."""
    path = sync_path_request_path()
    path.write_text(utc_now_iso() + "\n", encoding="utf-8")
    return path


def clear_pass_request() -> None:
    """Clear a pending path-trigger request (after a pass starts or is cancelled)."""
    try:
        sync_path_request_path().unlink(missing_ok=True)
    except OSError:
        pass


def pass_request_pending() -> bool:
    """True when a local path trigger asked for a pass that has not started yet."""
    try:
        return sync_path_request_path().is_file()
    except OSError:
        return False


def debounce_ready(
    last_event_mono: float | None,
    *,
    now_mono: float,
    debounce_seconds: float = PATH_TRIGGER_DEBOUNCE_SECONDS,
) -> bool:
    """True when ``debounce_seconds`` have elapsed since ``last_event_mono``."""
    if last_event_mono is None:
        return False
    if debounce_seconds <= 0:
        return True
    return (now_mono - last_event_mono) >= float(debounce_seconds)


def local_watch_available() -> bool:
    """True when this process can install a Gio directory monitor (inotify on Linux)."""
    if sys.platform != "linux":
        return False
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # noqa: F401
    except Exception:
        return False
    return True


class GioTreeMonitor:
    """Recursive directory monitors via Gio (inotify backend on Linux).

    New subdirectories get a watch when created. Caps at ``_MAX_MONITORS``.
    Degrades quietly when Gio cannot watch a path.
    """

    def __init__(
        self,
        root: str | Path,
        on_change: Callable[[], Any],
        *,
        max_monitors: int = _MAX_MONITORS,
    ) -> None:
        self._root = Path(root).expanduser().resolve()
        self._on_change = on_change
        self._max = max(1, int(max_monitors))
        self._monitors: list[Any] = []
        self._watched: set[str] = set()

    @property
    def root(self) -> Path:
        return self._root

    def start(self) -> bool:
        """Install monitors under ``root``. Returns False if none could be added."""
        self.stop()
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        self._watch_dir(self._root)
        try:
            for dirpath, dirnames, _filenames in os.walk(self._root):
                if len(self._monitors) >= self._max:
                    break
                for name in dirnames:
                    if len(self._monitors) >= self._max:
                        break
                    self._watch_dir(Path(dirpath) / name)
        except OSError:
            pass
        return bool(self._monitors)

    def stop(self) -> None:
        for monitor in self._monitors:
            try:
                monitor.cancel()
            except Exception:
                pass
        self._monitors.clear()
        self._watched.clear()

    def _watch_dir(self, path: Path) -> None:
        if len(self._monitors) >= self._max:
            return
        try:
            resolved = str(path.resolve())
        except OSError:
            return
        if resolved in self._watched:
            return
        if not path.is_dir():
            return
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
        except Exception:
            return
        try:
            gfile = Gio.File.new_for_path(resolved)
            monitor = gfile.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except Exception:
            return
        if monitor is None:
            return
        monitor.connect("changed", self._on_monitor_changed)
        self._monitors.append(monitor)
        self._watched.add(resolved)

    def _on_monitor_changed(self, _monitor, file, _other, event_type) -> None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
        except Exception:
            self._on_change()
            return
        path_str = file.get_path() if file is not None else None
        if path_str and event_type in (
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.RENAMED,
            Gio.FileMonitorEvent.MOVED_IN,
        ):
            candidate = Path(path_str)
            if candidate.is_dir():
                self._watch_dir(candidate)
        # Ignore attribute-only noise when possible; still fire for content edits.
        if event_type == Gio.FileMonitorEvent.ATTRIBUTE_CHANGED:
            return
        self._on_change()


class MultiGioTreeMonitor:
    """Watch several always-on local roots with one shared change callback."""

    def __init__(
        self,
        roots: list[str | Path],
        on_change: Callable[[], Any],
        *,
        max_monitors: int = _MAX_MONITORS,
    ) -> None:
        self._on_change = on_change
        self._max = max(1, int(max_monitors))
        self._monitors: list[GioTreeMonitor] = []
        self._roots: list[Path] = []
        for root in roots:
            path = Path(root).expanduser()
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            self._roots.append(resolved)

    @property
    def roots(self) -> list[Path]:
        return list(self._roots)

    @property
    def root(self) -> Path:
        """Primary root (first pair) for callers that expect a single path."""
        return self._roots[0] if self._roots else Path()

    def start(self) -> bool:
        self.stop()
        remaining = self._max
        for root in self._roots:
            if remaining <= 0:
                break
            monitor = GioTreeMonitor(root, self._on_change, max_monitors=remaining)
            if monitor.start():
                used = len(monitor._monitors)
                self._monitors.append(monitor)
                remaining = max(0, remaining - used)
        return bool(self._monitors)

    def stop(self) -> None:
        for monitor in self._monitors:
            monitor.stop()
        self._monitors.clear()
