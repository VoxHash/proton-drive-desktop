"""Best-effort deep name search via official ``filesystem list`` walks.

Opsec notes (Proton Drive GUI wrapper):
- Uses only the signed-in official CLI (no undocumented HTTP APIs).
- Matches **names** from list metadata only — no content indexing, no local
  search database, no file-body reads.
- Results stay in memory for the active search session; nothing is written to
  disk beyond normal CLI session/cache under Proton’s own paths.
- Progress callbacks should avoid logging full remote trees to journald.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .cli import CliError, ProtonDriveCli, join_path, node_name


DEEP_SEARCH_SCOPE_FILTER = "filter"
DEEP_SEARCH_SCOPE_CURRENT = "deep-current"
DEEP_SEARCH_SCOPE_MY_FILES = "deep-my-files"
DEEP_SEARCH_SCOPE_SHARED = "deep-shared"

DEEP_SEARCH_SCOPES: tuple[str, ...] = (
    DEEP_SEARCH_SCOPE_FILTER,
    DEEP_SEARCH_SCOPE_CURRENT,
    DEEP_SEARCH_SCOPE_MY_FILES,
    DEEP_SEARCH_SCOPE_SHARED,
)


class DeepSearchCancelled(Exception):
    """Raised when the user cancels an in-flight deep walk."""


@dataclass(frozen=True)
class DeepSearchHit:
    """One name match from a ``filesystem list`` entry (metadata only)."""

    name: str
    path: str
    kind: str
    node: dict[str, Any]


def normalize_deep_search_scope(value: object) -> str:
    key = str(value or "").strip().lower()
    if key in DEEP_SEARCH_SCOPES:
        return key
    return DEEP_SEARCH_SCOPE_FILTER


def deep_search_root(
    scope: str,
    *,
    current_path: str,
    section: str,
) -> str | None:
    """Return the remote root to walk, or ``None`` for in-folder filter mode.

    Deep search is limited to My files / Shared trees (downloadable filesystem
    sections). Photos / Trash are not walked (CLI list semantics differ).
    """
    scope = normalize_deep_search_scope(scope)
    if scope == DEEP_SEARCH_SCOPE_FILTER:
        return None
    if scope == DEEP_SEARCH_SCOPE_MY_FILES:
        return "/my-files"
    if scope == DEEP_SEARCH_SCOPE_SHARED:
        return "/shared-with-me"
    # deep-current: walk the current folder subtree when under my-files or shared
    path = str(current_path or "").strip() or "/my-files"
    sec = str(section or "")
    if sec == "/my-files" or path == "/my-files" or path.startswith("/my-files/"):
        return path if path.startswith("/my-files") else "/my-files"
    if sec == "/shared-with-me" or path == "/shared-with-me" or path.startswith("/shared-with-me/"):
        return path if path.startswith("/shared-with-me") else "/shared-with-me"
    return None


def deep_search_scope_allowed(scope: str, *, section: str) -> bool:
    """Whether the UI should offer *scope* for the active sidebar section."""
    scope = normalize_deep_search_scope(scope)
    if scope == DEEP_SEARCH_SCOPE_FILTER:
        return True
    if scope == DEEP_SEARCH_SCOPE_MY_FILES:
        return True
    if scope == DEEP_SEARCH_SCOPE_SHARED:
        return True
    if scope == DEEP_SEARCH_SCOPE_CURRENT:
        return section in {"/my-files", "/shared-with-me"}
    return False


def should_descend_folder(kind: str) -> bool:
    """Only descend into folders during a name walk (not albums/days/invites)."""
    return str(kind or "").strip().lower() == "folder"


def listing_name_matches(name: str, query: str) -> bool:
    """Case-insensitive substring match on a single display name."""
    needle = query.strip().casefold()
    if not needle:
        return True
    return needle in str(name or "").casefold()


ProgressCb = Callable[[int, str, int], None]


def walk_name_matches(
    cli: ProtonDriveCli,
    root: str,
    query: str,
    *,
    cancel: threading.Event | None = None,
    on_progress: ProgressCb | None = None,
    max_folders: int = 5000,
) -> list[DeepSearchHit]:
    """BFS walk with ``filesystem list``; match *query* against node names.

    Slow and rate-limit sensitive on large trees — one CLI list per folder.
    Does not read file contents. Empty *query* returns no hits (caller should
    use the local filter for empty needles).
    """
    needle = query.strip()
    if not needle:
        return []
    root = str(root or "").strip() or "/my-files"
    stop = cancel or threading.Event()
    matches: list[DeepSearchHit] = []
    queue: list[str] = [root]
    folders_seen = 0
    while queue:
        if stop.is_set():
            raise DeepSearchCancelled()
        path = queue.pop(0)
        try:
            nodes = cli.list(path)
        except CliError:
            if on_progress is not None:
                on_progress(folders_seen, path, len(matches))
            continue
        folders_seen += 1
        if on_progress is not None:
            # Pass folder path for UI status only — do not write to logs here.
            on_progress(folders_seen, path, len(matches))
        if folders_seen > max_folders:
            break
        for node in nodes or []:
            if stop.is_set():
                raise DeepSearchCancelled()
            if not isinstance(node, dict):
                continue
            name = node_name(node)
            kind = str(node.get("type") or "unknown")
            child = join_path(path, name)
            if listing_name_matches(name, needle):
                matches.append(DeepSearchHit(name=name, path=child, kind=kind, node=dict(node)))
            if should_descend_folder(kind):
                queue.append(child)
    return matches
