"""GTK4 / libadwaita desktop UI for the official Proton Drive CLI."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import __version__
from .cli import (
    CliError,
    CliVersionInfo,
    NotLoggedIn,
    ProtonDriveCli,
    TransferCancelled,
    TransferProgress,
    account_email,
    added_by_email,
    album_cli_path,
    cli_help_exposes_storage_quota,
    find_binary,
    format_size,
    invitation_name,
    invitation_uid,
    join_path,
    member_email,
    member_role,
    node_name,
    node_size,
    parse_version_output,
    photo_cli_path,
)
from .config import (
    SYNC_INTERVAL_SECONDS_MAX,
    SYNC_INTERVAL_SECONDS_MIN,
    SYNC_PASS_TIMEOUT_SECONDS_MAX,
    SYNC_PASS_TIMEOUT_SECONDS_MIN,
    SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED,
    apply_theme,
    download_folder,
    empty_sync_pair,
    ensure_sync_pairs,
    load as load_config,
    normalize_sync_conflict_policy,
    normalize_sync_direction,
    normalize_sync_interval_seconds,
    normalize_sync_pass_timeout_seconds,
    normalize_sync_remote_root,
    save as save_config,
    set_gui_busy,
    sync_folder as configured_sync_folder,
    sync_pair_local_paths,
)
from .i18n import _, apply_gtk_direction, language_choices, ngettext, normalize_language, restore_session_locale_env
from .cli_verify import verify_proton_drive_binary
from .notify import notify_worker_failure
from .path_trigger import (
    PATH_TRIGGER_DEBOUNCE_SECONDS,
    GioTreeMonitor,
    MultiGioTreeMonitor,
    local_watch_available,
    request_pass_soon,
)
from .sync import (
    activity_snapshot,
    due_for_pass,
    format_preview_message,
    format_seed_message,
    format_status_line,
    mark_worker_idle,
    mark_worker_paused,
    mark_worker_stopped,
    preview_pass,
    seed_sync_delta,
    spawn_worker,
    sync_is_paused,
)
from .paths import (
    ACCOUNT_URL,
    APP_ICON_NAME,
    APP_ID,
    CLI_DOWNLOAD_URL,
    CLI_HELP_URL,
    DRIVE_WEB_URL,
    HELP_URL,
    ISSUE_URL,
    PRIVACY_URL,
    TERMS_URL,
    WEBSITE_URL,
    cli_data_dir,
    hicolor_dir,
    icon_png,
    icon_theme_search_path,
    repo_root,
    sync_systemd_path_unit_path,
    xdg_autostart_path,
)
from .systemd_sync import (
    set_sync_path_trigger,
    set_sync_systemd,
    sync_path_unit_is_enabled,
    sync_timer_is_enabled,
    systemd_user_available,
)
from .tray import StatusNotifierTray
from .transfer_queue import QueueSnapshot, TransferJob, TransferQueue
_UNSHAREABLE_ROOTS = {"/my-files", "/photos", "/shared-with-me", "/trash"}
_INVITE_ROLES = ("viewer", "editor", "admin")
_LINK_ROLES = ("viewer", "editor")


def _sections() -> tuple[tuple[str, str, str], ...]:
    return (
        (_("My files"), "/my-files", "folder-documents-symbolic"),
        (_("Photos"), "/photos", "folder-pictures-symbolic"),
        (_("Shared with me"), "/shared-with-me", "system-users-symbolic"),
        (_("Trash"), "/trash", "user-trash-symbolic"),
    )


def _item_count(count: int) -> str:
    return ngettext("{count} item", "{count} items", count).format(count=count)


def listing_name_matches(name: str, query: str) -> bool:
    """Case-insensitive substring match for in-list folder filtering (Ctrl+F)."""
    needle = query.strip().casefold()
    if not needle:
        return True
    return needle in name.casefold()


_NON_DOWNLOADABLE_KINDS = frozenset({"day", "album", "invitation"})
_NON_MOVABLE_KINDS = frozenset({"invitation", "day", "album"})


def is_downloadable_kind(kind: str) -> bool:
    """True when toolbar Download can run proton-drive filesystem/photo download."""
    return kind not in _NON_DOWNLOADABLE_KINDS


def is_movable_item(kind: str, path: str, section: str) -> bool:
    """True when Move can run proton-drive filesystem move on this listing row."""
    if kind in _NON_MOVABLE_KINDS:
        return False
    if section == "/trash" or path.startswith("/trash"):
        return False
    if path in _UNSHAREABLE_ROOTS:
        return False
    return True


def dest_is_inside_source(dest: str, source: str) -> bool:
    """True when dest is the source path or a child of it (illegal move target)."""
    if dest == source:
        return True
    prefix = source.rstrip("/") + "/"
    return dest.startswith(prefix)


def crumbs_after_navigate(
    crumbs: list[tuple[str, str]], index: int
) -> list[tuple[str, str]] | None:
    """Return crumb trail truncated to *index* (inclusive), or None if no-op."""
    if index < 0 or index >= len(crumbs):
        return None
    if index == len(crumbs) - 1:
        return None
    return crumbs[: index + 1]


def normalize_view_mode(value: object) -> str:
    """Return ``list`` or ``grid`` for the file browser view preference."""
    return "grid" if str(value or "").strip().lower() == "grid" else "list"


_DEFAULT_WINDOW_WIDTH = 1180
_DEFAULT_WINDOW_HEIGHT = 760
_SECTION_ROOTS = ("/my-files", "/photos", "/shared-with-me", "/trash")


def section_for_path(path: str) -> str:
    """Map a remote Drive path to its sidebar section root."""
    p = str(path or "").strip() or "/my-files"
    if p == "/photos" or p.startswith("/photos/") or p.startswith("/albums"):
        return "/photos"
    if p == "/shared-with-me" or p.startswith("/shared-with-me/"):
        return "/shared-with-me"
    if p == "/trash" or p.startswith("/trash/"):
        return "/trash"
    if p == "/my-files" or p.startswith("/my-files/"):
        return "/my-files"
    return "/my-files"


def normalize_last_path(value: object) -> str:
    """Return a usable remote path, or ``/my-files`` when the value is unknown."""
    path = str(value or "").strip()
    if not path.startswith("/"):
        return "/my-files"
    while path.endswith("/") and path != "/":
        path = path[:-1]
    if path in _SECTION_ROOTS:
        return path
    for prefix in ("/my-files/", "/photos/", "/shared-with-me/", "/trash/", "/albums/"):
        if path.startswith(prefix) and len(path) > len(prefix):
            return path
    if path == "/albums":
        return "/photos"
    return "/my-files"


def normalize_window_width(value: object) -> int:
    try:
        width = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_WIDTH
    if width <= 0:
        return _DEFAULT_WINDOW_WIDTH
    return max(400, min(width, 10000))


def normalize_window_height(value: object) -> int:
    try:
        height = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_HEIGHT
    if height <= 0:
        return _DEFAULT_WINDOW_HEIGHT
    return max(300, min(height, 10000))


def _split_escaped_segments(rest: str) -> list[str]:
    """Split a path remainder on unescaped ``/`` into unescaped segment names."""
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(rest):
        ch = rest[i]
        if ch == "\\" and i + 1 < len(rest):
            buf.append(rest[i + 1])
            i += 2
            continue
        if ch == "/":
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [seg for seg in segments if seg]


def crumbs_for_path(path: str) -> list[tuple[str, str]]:
    """Build breadcrumb ``(label, path)`` pairs for a remote Drive path."""
    path = normalize_last_path(path)
    section = section_for_path(path)
    labels = {root: name for name, root, _icon in _sections()}
    root_label = labels.get(section, section)
    if path.startswith("/albums/"):
        segs = _split_escaped_segments(path[len("/albums/") :])
        display = segs[-1] if segs else path.rsplit("/", 1)[-1]
        return [(root_label, "/photos"), (display, path)]
    if path == section:
        return [(root_label, section)]
    if not path.startswith(section + "/"):
        return [(root_label, section)]
    rest = path[len(section) + 1 :]
    segs = _split_escaped_segments(rest)
    crumbs: list[tuple[str, str]] = [(root_label, section)]
    acc = section
    for seg in segs:
        acc = join_path(acc, seg)
        day = _photos_day(acc) if section == "/photos" else None
        label = _format_day(day) if day else seg
        crumbs.append((label, acc))
    return crumbs


_EXT_ICONS: dict[str, str] = {
    ".7z": "package-x-generic",
    ".aac": "audio-x-generic",
    ".avi": "video-x-generic",
    ".bmp": "image-x-generic",
    ".c": "text-x-generic",
    ".cpp": "text-x-generic",
    ".css": "text-css",
    ".csv": "text-csv",
    ".doc": "x-office-document",
    ".docx": "x-office-document",
    ".flac": "audio-x-generic",
    ".flv": "video-x-generic",
    ".gif": "image-x-generic",
    ".go": "text-x-generic",
    ".gz": "package-x-generic",
    ".heic": "image-x-generic",
    ".htm": "text-html",
    ".html": "text-html",
    ".ico": "image-x-generic",
    ".java": "text-x-generic",
    ".jpeg": "image-x-generic",
    ".jpg": "image-x-generic",
    ".js": "text-x-script",
    ".json": "text-x-generic",
    ".m4a": "audio-x-generic",
    ".md": "text-x-generic",
    ".mkv": "video-x-generic",
    ".mov": "video-x-generic",
    ".mp3": "audio-x-generic",
    ".mp4": "video-x-generic",
    ".odp": "x-office-presentation",
    ".ods": "x-office-spreadsheet",
    ".odt": "x-office-document",
    ".ogg": "audio-x-generic",
    ".pdf": "application-pdf",
    ".png": "image-x-generic",
    ".ppt": "x-office-presentation",
    ".pptx": "x-office-presentation",
    ".py": "text-x-script",
    ".rar": "package-x-generic",
    ".rs": "text-x-generic",
    ".rtf": "x-office-document",
    ".svg": "image-x-generic",
    ".tar": "package-x-generic",
    ".tgz": "package-x-generic",
    ".ts": "text-x-script",
    ".txt": "text-x-generic",
    ".wav": "audio-x-generic",
    ".webm": "video-x-generic",
    ".webp": "image-x-generic",
    ".xls": "x-office-spreadsheet",
    ".xlsx": "x-office-spreadsheet",
    ".xml": "text-xml",
    ".yaml": "text-x-generic",
    ".yml": "text-x-generic",
    ".zip": "package-x-generic",
}

_MIME_ICONS: dict[str, str] = {
    "application/pdf": "application-pdf",
    "application/zip": "package-x-generic",
    "application/x-7z-compressed": "package-x-generic",
    "application/x-rar-compressed": "package-x-generic",
    "application/gzip": "package-x-generic",
    "application/x-tar": "package-x-generic",
    "application/json": "text-x-generic",
    "application/xml": "text-xml",
    "text/csv": "text-csv",
    "text/html": "text-html",
    "text/css": "text-css",
    "text/javascript": "text-x-script",
    "application/javascript": "text-x-script",
    "application/typescript": "text-x-script",
    "application/msword": "x-office-document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "x-office-document",
    "application/vnd.oasis.opendocument.text": "x-office-document",
    "application/vnd.ms-excel": "x-office-spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "x-office-spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet": "x-office-spreadsheet",
    "application/vnd.ms-powerpoint": "x-office-presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "x-office-presentation",
    "application/vnd.oasis.opendocument.presentation": "x-office-presentation",
}


def file_type_icon(*, kind: str, name: str = "", media_type: str = "") -> str:
    """Pick a themed icon name from Drive item kind, MIME, or filename extension."""
    kind_l = (kind or "").lower()
    if kind_l == "folder":
        return "folder"
    if kind_l == "invitation":
        return "mail-unread-symbolic"
    if kind_l in ("day", "album"):
        return "folder-pictures"
    if kind_l == "photo":
        media = (media_type or "").lower()
        if media.startswith("video"):
            return "video-x-generic"
        return "image-x-generic"

    mime = (media_type or "").strip().lower()
    if mime:
        if mime in _MIME_ICONS:
            return _MIME_ICONS[mime]
        if mime.startswith("image/"):
            return "image-x-generic"
        if mime.startswith("video/"):
            return "video-x-generic"
        if mime.startswith("audio/"):
            return "audio-x-generic"
        if mime.startswith("text/"):
            return "text-html" if "html" in mime else "text-x-generic"
        if any(token in mime for token in ("zip", "compressed", "archive", "tar", "gzip")):
            return "package-x-generic"
        if "spreadsheet" in mime or "excel" in mime:
            return "x-office-spreadsheet"
        if "presentation" in mime or "powerpoint" in mime:
            return "x-office-presentation"
        if "wordprocessing" in mime or "msword" in mime or "opendocument.text" in mime:
            return "x-office-document"

    ext = Path(name or "").suffix.lower()
    if ext in _EXT_ICONS:
        return _EXT_ICONS[ext]

    if name:
        guessed, _uncertain = Gio.content_type_guess(name, None)
        if guessed:
            mapped = _MIME_ICONS.get(guessed.lower())
            if mapped:
                return mapped
            if guessed.startswith("image/"):
                return "image-x-generic"
            if guessed.startswith("video/"):
                return "video-x-generic"
            if guessed.startswith("audio/"):
                return "audio-x-generic"
            gicon = Gio.content_type_get_icon(guessed)
            if isinstance(gicon, Gio.ThemedIcon):
                for candidate in gicon.get_names():
                    if candidate:
                        return candidate
    return "text-x-generic"


def _css_path() -> str:
    return str(Path(__file__).resolve().parent.parent / "data" / "style.css")


class DriveItem(GObject.GObject):
    def __init__(self, node: dict, path: str) -> None:
        super().__init__()
        self.node = node
        self.path = path
        self.name = node_name(node)
        self.kind = str(node.get("type") or "unknown")
        self.modified = str(node.get("modificationTime") or "")
        self.size = node_size(node)
        self.shared = bool(node.get("isShared") or node.get("isSharedByUrl"))


def _format_when(iso: str) -> str:
    if not iso:
        return "—"
    try:
        when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return when.strftime("%b %d, %Y %H:%M")
    except ValueError:
        return iso


def format_item_type(kind: str) -> str:
    """Human label for a listing node type from the official CLI."""
    key = (kind or "").strip().lower()
    labels = {
        "file": _("File"),
        "folder": _("Folder"),
        "photo": _("Photo"),
        "album": _("Album"),
        "day": _("Day"),
        "invitation": _("Invitation"),
    }
    if key in labels:
        return labels[key]
    if key:
        return key.replace("-", " ").title()
    return _("Unknown")


def format_share_status(*, is_shared: bool = False, is_shared_by_url: bool = False) -> str:
    """Share status from listing ``isShared`` / ``isSharedByUrl`` flags."""
    if is_shared and is_shared_by_url:
        return _("Shared (people and link)")
    if is_shared:
        return _("Shared")
    if is_shared_by_url:
        return _("Shared via link")
    return _("Not shared")


def item_property_rows(
    *,
    name: str,
    kind: str,
    size: int | None,
    modified: str,
    path: str,
    is_shared: bool = False,
    is_shared_by_url: bool = False,
) -> list[tuple[str, str]]:
    """Read-only Properties fields from listing data (no invented metadata)."""
    return [
        (_("Name"), name or "—"),
        (_("Type"), format_item_type(kind)),
        (_("Size"), format_size(size)),
        (_("Modified"), _format_when(modified)),
        (
            _("Share status"),
            format_share_status(is_shared=is_shared, is_shared_by_url=is_shared_by_url),
        ),
        (_("Full path"), path or "—"),
    ]


def _format_day(iso_date: str) -> str:
    try:
        return dt.datetime.strptime(iso_date, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return iso_date


def _photos_day(path: str) -> str | None:
    prefix = "/photos/"
    if not path.startswith(prefix):
        return None
    day = path[len(prefix) :]
    if len(day) == 10 and day[4] == "-" and day[7] == "-":
        return day
    return None


def _photos_album_path(path: str) -> str | None:
    prefix = "/albums/"
    if path.startswith(prefix) and path != prefix:
        return path
    return None


class DriveWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=_("Proton Drive"))
        cfg = load_config()
        width = normalize_window_width(cfg.get("window_width"))
        height = normalize_window_height(cfg.get("window_height"))
        self.set_default_size(width, height)
        if bool(cfg.get("window_maximized")):
            self.maximize()
        self.cli = ProtonDriveCli()
        restored = normalize_last_path(cfg.get("last_path"))
        self.section = section_for_path(restored)
        self.current_path = restored
        self.crumbs: list[tuple[str, str]] = crumbs_for_path(restored)
        self._pending_path_restore = self.current_path != self.section
        self.busy = False
        self.email = ""
        self.store = Gio.ListStore.new(DriveItem)
        self._search_query = ""
        self._listing_status_extra = ""
        self._timeline_cache: list | None = None
        self._transfer_fatal = False
        self._last_download_folder: str | None = None
        self._window_persist_source = 0
        self._view_mode = normalize_view_mode(cfg.get("view_mode"))
        self.set_icon_name(APP_ICON_NAME)
        self._init_transfer_queue()
        self._build()
        self.connect("notify::default-width", self._schedule_persist_window)
        self.connect("notify::default-height", self._schedule_persist_window)
        self.connect("notify::maximized", self._schedule_persist_window)
        self.reload()

    def _init_transfer_queue(self) -> None:
        self.transfers = TransferQueue(
            cancel_cli=self.cli.cancel_transfer,
            on_started=lambda job, snap: GLib.idle_add(self._on_transfer_started, job, snap),
            on_progress=lambda progress, snap: GLib.idle_add(self._apply_transfer_progress, progress, snap),
            on_finished=lambda job, result, snap: GLib.idle_add(self._on_transfer_finished, job, result, snap),
            on_error=lambda job, exc, snap: GLib.idle_add(self._on_transfer_error, job, exc, snap),
            on_idle=lambda: GLib.idle_add(self._on_transfers_idle),
            on_changed=lambda snap: GLib.idle_add(self._on_transfer_queue_changed, snap),
        )

    def _build(self) -> None:
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        split = Adw.NavigationSplitView(min_sidebar_width=240, max_sidebar_width=320)
        self.toasts.set_child(split)

        sidebar_page = Adw.NavigationPage(title=_("Proton Drive"))
        sidebar_toolbar = Adw.ToolbarView()
        sidebar_page.set_child(sidebar_toolbar)
        side_header = Adw.HeaderBar()
        title = Adw.WindowTitle(title=_("Proton Drive"), subtitle=_("Linux · official CLI"))
        side_header.set_title_widget(title)
        sidebar_toolbar.add_top_bar(side_header)

        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.side_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["navigation-sidebar"])
        self.side_list.connect("row-activated", self._on_section)
        for label, path, icon in _sections():
            row = Gtk.ListBoxRow()
            row.path = path  # type: ignore[attr-defined]
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_start=12, margin_end=12, margin_top=10, margin_bottom=10)
            box.append(Gtk.Image.new_from_icon_name(icon))
            box.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            row.set_child(box)
            self.side_list.append(row)
        section_paths = [p for _n, p, _i in _sections()]
        try:
            side_index = section_paths.index(self.section)
        except ValueError:
            side_index = 0
        self.side_list.select_row(self.side_list.get_row_at_index(side_index))
        side_box.append(self.side_list)
        side_box.append(Gtk.Separator())
        self.account_label = Gtk.Label(
            label=_("Checking session…"),
            xalign=0,
            wrap=True,
            margin_start=16,
            margin_end=16,
            margin_top=12,
            margin_bottom=4,
            css_classes=["dim-label"],
        )
        side_box.append(self.account_label)
        self.version_label = Gtk.Label(
            label="",
            xalign=0,
            wrap=True,
            margin_start=16,
            margin_end=16,
            margin_bottom=8,
            css_classes=["dim-label"],
        )
        side_box.append(self.version_label)
        self.sync_label = Gtk.Label(
            label=format_status_line(),
            xalign=0,
            wrap=True,
            margin_start=16,
            margin_end=16,
            margin_bottom=16,
            css_classes=["dim-label"],
        )
        side_box.append(self.sync_label)
        sidebar_toolbar.set_content(side_box)
        split.set_sidebar(sidebar_page)

        content_page = Adw.NavigationPage(title=_("Files"))
        content_toolbar = Adw.ToolbarView()
        content_page.set_child(content_toolbar)
        header = Adw.HeaderBar()
        self.breadcrumb_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=2,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
        )
        self.breadcrumb_box.set_tooltip_text("/my-files")
        header.set_title_widget(self.breadcrumb_box)
        self._rebuild_breadcrumbs()

        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=_("Back"))
        self.back_btn.connect("clicked", lambda *_: self._go_up())
        header.pack_start(self.back_btn)

        self.search_btn = Gtk.ToggleButton(
            icon_name="system-search-symbolic",
            tooltip_text=_("Filter current folder (Ctrl+F)"),
        )
        header.pack_start(self.search_btn)

        self.view_btn = Gtk.Button()
        self.view_btn.connect("clicked", self._toggle_view_mode)
        header.pack_start(self.view_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text=_("Menu"), primary=True)
        application = self.get_application()
        if isinstance(application, DriveApp):
            menu_btn.set_menu_model(application.app_menu)
        header.pack_end(menu_btn)

        self.trash_btn: Gtk.Button | None = None
        self.delete_permanently_btn: Gtk.Button | None = None
        self.empty_trash_btn: Gtk.Button | None = None
        self.new_folder_btn: Gtk.Button | None = None
        self.copy_btn: Gtk.Button | None = None
        for icon, tip, handler, key in (
            ("folder-new-symbolic", _("New folder"), self._new_folder, "new_folder_btn"),
            ("document-save-symbolic", _("Upload"), self._upload, None),
            ("folder-download-symbolic", _("Download"), self._download, None),
            ("emblem-shared-symbolic", _("Share or invitations"), self._share, None),
            ("document-edit-symbolic", _("Rename"), self._rename, None),
            ("edit-copy-symbolic", _("Copy"), self._copy, "copy_btn"),
            ("send-to-symbolic", _("Move"), self._move, None),
            ("document-open-symbolic", _("Open"), self._open_selected, None),
            ("user-trash-symbolic", _("Move to trash"), self._trash, "trash_btn"),
            ("edit-delete-symbolic", _("Delete permanently"), self._delete_permanently, "delete_permanently_btn"),
            ("user-trash-full-symbolic", _("Empty trash"), self._empty_trash, "empty_trash_btn"),
            ("view-refresh-symbolic", _("Refresh"), lambda *_: self.reload(), None),
        ):
            btn = Gtk.Button(icon_name=icon, tooltip_text=tip)
            btn.connect("clicked", handler)
            header.pack_end(btn)
            if key:
                setattr(self, key, btn)
        if self.delete_permanently_btn is not None:
            self.delete_permanently_btn.set_visible(False)
        if self.empty_trash_btn is not None:
            self.empty_trash_btn.set_visible(False)

        self.login_btn = Gtk.Button(label=_("Sign in"), css_classes=["suggested-action"], visible=False)
        self.login_btn.connect("clicked", self._login)
        header.pack_end(self.login_btn)

        content_toolbar.add_top_bar(header)

        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Filter current folder…"), hexpand=True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("stop-search", self._on_stop_search)
        self.search_bar = Gtk.SearchBar(show_close_button=True)
        self.search_bar.set_child(self.search_entry)
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.bind_property(
            "search-mode-enabled",
            self.search_btn,
            "active",
            GObject.BindingFlags.BIDIRECTIONAL,
        )
        content_toolbar.add_top_bar(self.search_bar)

        self.status = Gtk.Label(xalign=0, margin_start=16, margin_end=16, margin_top=6, margin_bottom=6, css_classes=["dim-label"])
        content_toolbar.add_bottom_bar(self.status)

        self.stack = Gtk.Stack()
        self.spinner = Gtk.Spinner()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, spacing=12)
        loading.append(self.spinner)
        self.busy_label = Gtk.Label(label=_("Loading Proton Drive…"))
        loading.append(self.busy_label)
        self.progress_bar = Gtk.ProgressBar(show_text=True, width_request=280, visible=False)
        loading.append(self.progress_bar)
        transfer_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        self.cancel_transfer_btn = Gtk.Button(label=_("Cancel transfer"), visible=False)
        self.cancel_transfer_btn.connect("clicked", self._cancel_active_transfer)
        self.clear_queue_btn = Gtk.Button(label=_("Clear queue"), visible=False)
        self.clear_queue_btn.connect("clicked", self._clear_transfer_queue)
        transfer_actions.append(self.cancel_transfer_btn)
        transfer_actions.append(self.clear_queue_btn)
        loading.append(transfer_actions)
        self.stack.add_named(loading, "loading")

        self.empty = Adw.StatusPage(
            icon_name="folder-symbolic",
            title=_("This folder is empty"),
            description=_("Upload files with the official Proton Drive CLI session on this machine."),
        )
        self.stack.add_named(self.empty, "empty")

        self.error_page = Adw.StatusPage(icon_name="dialog-error-symbolic", title=_("Could not load Drive"))
        signin = Gtk.Button(label=_("Sign in with Proton"), css_classes=["suggested-action", "pill"], halign=Gtk.Align.CENTER)
        signin.connect("clicked", self._login)
        self.error_page.set_child(signin)
        self.stack.add_named(self.error_page, "error")

        scrolled = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.files_scrolled = scrolled
        self.name_filter = Gtk.CustomFilter.new(self._filter_item)
        self.filtered_store = Gtk.FilterListModel(model=self.store, filter=self.name_filter)
        self.selection = Gtk.MultiSelection.new(self.filtered_store)
        self.column = Gtk.ColumnView(show_column_separators=False, show_row_separators=True, enable_rubberband=True)
        self.column.connect("activate", self._on_activate)
        grid_factory = Gtk.SignalListItemFactory()
        grid_factory.connect("setup", self._grid_setup)
        grid_factory.connect("bind", self._grid_bind)
        self.grid = Gtk.GridView(
            factory=grid_factory,
            max_columns=12,
            min_columns=1,
            single_click_activate=False,
            enable_rubberband=True,
        )
        self.grid.connect("activate", self._on_activate)
        for view in (self.column, self.grid):
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._on_key)
            view.add_controller(keys)
            right_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
            right_click.connect("pressed", self._on_item_context)
            view.add_controller(right_click)
        self._item_popover: Gtk.Popover | None = None
        self._add_column(_("Name"), self._name_setup, self._name_bind, expand=True)
        self._add_column(_("Modified"), self._label_setup, self._modified_bind, width=170)
        self._add_column(_("Size"), self._label_setup, self._size_bind, width=110)
        self._apply_view_mode(self._view_mode, persist=False)
        self.stack.add_named(scrolled, "list")
        content_toolbar.set_content(self.stack)
        split.set_content(content_page)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_files_dropped)
        self.stack.add_controller(drop)

        find = Gio.SimpleAction.new("find", None)
        find.connect("activate", self._toggle_search)
        self.add_action(find)
        application = self.get_application()
        if application is not None:
            application.set_accels_for_action("win.find", ["<Primary>f"])

        self._bg(self.cli.version_info, self._on_version, self._on_version_error)

    def _add_column(self, title: str, setup, bind, expand: bool = False, width: int = 0) -> None:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", setup)
        factory.connect("bind", bind)
        col = Gtk.ColumnViewColumn(title=title, factory=factory, expand=expand, resizable=True)
        if width:
            col.set_fixed_width(width)
        self.column.append_column(col)

    def _label_setup(self, _factory, list_item) -> None:
        list_item.set_child(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END))

    def _name_setup(self, _factory, list_item) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Image())
        box.append(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True))
        list_item.set_child(box)

    def _name_bind(self, _factory, list_item) -> None:
        item: DriveItem = list_item.get_item()
        box = list_item.get_child()
        image = box.get_first_child()
        label = image.get_next_sibling()
        image.set_pixel_size(18)
        image.set_from_icon_name(
            file_type_icon(
                kind=item.kind,
                name=item.name,
                media_type=str(item.node.get("mediaType") or ""),
            )
        )
        label.set_text(item.name)
        label.set_tooltip_text(item.path)

    def _grid_setup(self, _factory, list_item) -> None:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            margin_top=8,
            margin_bottom=8,
            margin_start=8,
            margin_end=8,
            css_classes=["file-grid-item"],
        )
        box.set_size_request(104, 104)
        image = Gtk.Image(halign=Gtk.Align.CENTER)
        image.set_pixel_size(48)
        label = Gtk.Label(
            xalign=0.5,
            justify=Gtk.Justification.CENTER,
            ellipsize=Pango.EllipsizeMode.END,
            wrap=True,
            lines=2,
            max_width_chars=12,
            width_chars=10,
        )
        box.append(image)
        box.append(label)
        list_item.set_child(box)

    def _grid_bind(self, _factory, list_item) -> None:
        item: DriveItem = list_item.get_item()
        box = list_item.get_child()
        image = box.get_first_child()
        label = image.get_next_sibling()
        image.set_from_icon_name(
            file_type_icon(
                kind=item.kind,
                name=item.name,
                media_type=str(item.node.get("mediaType") or ""),
            )
        )
        label.set_text(item.name)
        label.set_tooltip_text(item.path)

    def _active_files_view(self) -> Gtk.Widget:
        return self.grid if self._view_mode == "grid" else self.column

    def _apply_view_mode(self, mode: str, *, persist: bool = True) -> None:
        mode = normalize_view_mode(mode)
        self._view_mode = mode
        if mode == "grid":
            self.column.set_model(None)
            self.grid.set_model(self.selection)
            self.files_scrolled.set_child(self.grid)
            self.view_btn.set_icon_name("view-list-symbolic")
            self.view_btn.set_tooltip_text(_("List view"))
        else:
            self.grid.set_model(None)
            self.column.set_model(self.selection)
            self.files_scrolled.set_child(self.column)
            self.view_btn.set_icon_name("view-grid-symbolic")
            self.view_btn.set_tooltip_text(_("Grid view"))
        if persist:
            cfg = load_config()
            cfg["view_mode"] = mode
            save_config(cfg)

    def _toggle_view_mode(self, *_args) -> None:
        self._apply_view_mode("list" if self._view_mode == "grid" else "grid")

    def _schedule_persist_window(self, *_args) -> None:
        if self._window_persist_source:
            GLib.source_remove(self._window_persist_source)
        self._window_persist_source = GLib.timeout_add(400, self._persist_window_state)

    def _persist_window_state(self) -> bool:
        if self._window_persist_source:
            GLib.source_remove(self._window_persist_source)
            self._window_persist_source = 0
        width, height = self.get_default_size()
        cfg = load_config()
        cfg["window_width"] = normalize_window_width(width if width > 0 else _DEFAULT_WINDOW_WIDTH)
        cfg["window_height"] = normalize_window_height(height if height > 0 else _DEFAULT_WINDOW_HEIGHT)
        cfg["window_maximized"] = bool(self.is_maximized())
        save_config(cfg)
        return False

    def _persist_last_path(self) -> None:
        path = normalize_last_path(self.current_path)
        cfg = load_config()
        if cfg.get("last_path") == path:
            return
        cfg["last_path"] = path
        save_config(cfg)

    def _fall_back_to_section_root(self) -> None:
        """Reset navigation to the current section root after a stale last path."""
        labels = {p: n for n, p, _ in _sections()}
        root = self.section if self.section in labels else "/my-files"
        self.section = root
        self.current_path = root
        self.crumbs = [(labels.get(root, root), root)]
        self._pending_path_restore = False
        self._persist_last_path()
        self.reload()

    def _on_nav_error(self, exc: BaseException) -> None:
        if self._pending_path_restore and self.current_path != self.section:
            self._fall_back_to_section_root()
            return
        self._pending_path_restore = False
        self._fail(exc)

    def _modified_bind(self, _factory, list_item) -> None:
        item: DriveItem = list_item.get_item()
        list_item.get_child().set_text(_format_when(item.modified))

    def _size_bind(self, _factory, list_item) -> None:
        item: DriveItem = list_item.get_item()
        if item.kind == "folder":
            text = _("Folder")
        elif item.kind == "invitation":
            text = member_role(item.node).title()
        elif item.kind == "day":
            count = int(item.node.get("count") or 0)
            text = _item_count(count)
        elif item.kind == "album":
            count = (item.node.get("album") or {}).get("photoCount")
            text = _item_count(count) if isinstance(count, int) else _("Album")
        else:
            text = format_size(item.size)
        list_item.get_child().set_text(text)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        set_gui_busy(busy)
        self.spinner.set_spinning(busy)
        if busy:
            self.stack.set_visible_child_name("loading")
            text = message or _("Working…")
            self.status.set_text(text)
            self.busy_label.set_text(text)
            self.progress_bar.set_fraction(0.0)
            self.progress_bar.set_text("")
            self.progress_bar.set_visible(False)
            self._sync_transfer_action_buttons()
        else:
            self.progress_bar.set_visible(False)
            self.progress_bar.set_fraction(0.0)
            self.progress_bar.set_text("")
            self.cancel_transfer_btn.set_visible(False)
            self.clear_queue_btn.set_visible(False)

    def _transfer_status_message(self, job: TransferJob, snap: QueueSnapshot) -> str:
        if snap.pending_count:
            return _("{label} — {count} queued").format(label=job.label, count=snap.pending_count)
        return job.label

    def _sync_transfer_action_buttons(self, snap: QueueSnapshot | None = None) -> None:
        state = snap if snap is not None else self.transfers.snapshot()
        transferring = state.active is not None or state.pending_count > 0
        self.cancel_transfer_btn.set_visible(transferring and state.active is not None)
        self.clear_queue_btn.set_visible(state.pending_count > 0)

    def _on_transfer_queue_changed(self, snap: QueueSnapshot) -> bool:
        if snap.active is not None:
            text = self._transfer_status_message(snap.active, snap)
            self.status.set_text(text)
            if self.busy:
                self.busy_label.set_text(text)
        self._sync_transfer_action_buttons(snap)
        return False

    def _on_transfer_started(self, job: TransferJob, snap: QueueSnapshot) -> bool:
        message = self._transfer_status_message(job, snap)
        if not self.busy:
            self._set_busy(True, message)
        else:
            self.status.set_text(message)
            self.busy_label.set_text(message)
            self.progress_bar.set_fraction(0.0)
            self.progress_bar.set_text("")
            self.progress_bar.set_visible(False)
            self._sync_transfer_action_buttons(snap)
        return False

    def _apply_transfer_progress(self, progress: TransferProgress, snap: QueueSnapshot | None = None) -> bool:
        if not self.busy:
            return False
        state = snap if snap is not None else self.transfers.snapshot()
        text = progress.status_text()
        if text:
            if state.pending_count:
                text = _("{text} — {count} queued").format(text=text, count=state.pending_count)
            self.status.set_text(text)
            self.busy_label.set_text(text)
        if progress.percent is not None:
            fraction = max(0.0, min(1.0, progress.percent / 100.0))
            self.progress_bar.set_visible(True)
            self.progress_bar.set_fraction(fraction)
            label = f"{progress.percent:.1f}%"
            if progress.name:
                label = f"{progress.name} — {label}"
            if progress.size_label:
                label = f"{label} ({progress.size_label})"
            if state.pending_count:
                label = _("{label} — {count} queued").format(label=label, count=state.pending_count)
            self.progress_bar.set_text(label)
        elif progress.summary:
            self.progress_bar.set_visible(True)
            self.progress_bar.set_fraction(1.0)
            summary = progress.summary
            if state.pending_count:
                summary = _("{label} — {count} queued").format(label=summary, count=state.pending_count)
            self.progress_bar.set_text(summary)
        self._sync_transfer_action_buttons(state)
        return False

    def _on_transfer_finished(self, job: TransferJob, result: object, snap: QueueSnapshot) -> bool:
        if job.kind in ("download", "photo_download") and isinstance(result, str):
            self._last_download_folder = result
            self._toast(_("Saved to {folder}").format(folder=result))
        elif job.kind in ("upload", "photo_upload"):
            self._toast(_("Upload finished"))
        self._sync_transfer_action_buttons(snap)
        return False

    def _on_transfer_error(self, job: TransferJob, exc: BaseException, snap: QueueSnapshot) -> bool:
        self._sync_transfer_action_buttons(snap)
        if isinstance(exc, TransferCancelled):
            self._toast(_("Transfer cancelled"))
            return False
        if isinstance(exc, NotLoggedIn):
            self._transfer_fatal = True
            self.transfers.clear_pending()
            self._fail(exc)
            return False
        self._toast(str(exc)[:180])
        return False

    def _on_transfers_idle(self) -> bool:
        if self._transfer_fatal:
            self._transfer_fatal = False
            self.cancel_transfer_btn.set_visible(False)
            self.clear_queue_btn.set_visible(False)
            return False
        folder = self._last_download_folder
        self._last_download_folder = None
        self._set_busy(False)
        self.reload()
        if folder:
            subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False

    def _cancel_active_transfer(self, *_args) -> None:
        if not self.transfers.cancel_active():
            self._toast(_("No active transfer to cancel"))
            return
        self._toast(_("Cancelling transfer…"))

    def _clear_transfer_queue(self, *_args) -> None:
        cleared = self.transfers.clear_pending()
        if cleared:
            self._toast(ngettext("Cleared {count} queued transfer", "Cleared {count} queued transfers", cleared).format(count=cleared))
        self._sync_transfer_action_buttons()

    def _enqueue_transfer(self, kind: str, label: str, runner) -> None:
        snap = self.transfers.snapshot()
        queued_behind = snap.total_count > 0
        self.transfers.enqueue(kind, label, runner)
        if queued_behind:
            self._toast(_("Queued: {label}").format(label=label))
        elif not self.busy:
            self._set_busy(True, label)

    def _bg(self, fn, then, err=None):
        def work():
            try:
                result = fn()
                GLib.idle_add(then, result)
            except Exception as exc:  # noqa: BLE001 — surface any CLI failure in the UI
                GLib.idle_add(err or self._fail, exc)

        threading.Thread(target=work, daemon=True).start()

    def _fail(self, exc: BaseException) -> None:
        self._set_busy(False)
        if isinstance(exc, NotLoggedIn):
            self.error_page.set_title(_("Sign in required"))
            self.error_page.set_description(_("Use the same Proton browser login as the official CLI. Session is stored in the system keyring."))
            self.stack.set_visible_child_name("error")
            self.login_btn.set_visible(True)
            self.account_label.set_text(_("Not signed in"))
            if load_config().get("sync_enabled"):
                notify_worker_failure(str(exc), auth_expired=True)
            return
        self.error_page.set_title(_("Proton Drive CLI error"))
        self.error_page.set_description(str(exc)[:500])
        self.stack.set_visible_child_name("error")
        self._toast(str(exc)[:180])

    def _toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    def _on_version(self, info: CliVersionInfo) -> None:
        self.version_label.set_text(info.summary())
        self.version_label.set_tooltip_text(info.raw)

    def _on_version_error(self, exc: BaseException) -> None:
        self.version_label.set_text(str(exc)[:120])

    def _on_section(self, _list, row) -> None:
        path = getattr(row, "path", "/my-files")
        labels = {p: n for n, p, _ in _sections()}
        self.section = path
        self.current_path = path
        self.crumbs = [(labels.get(path, path), path)]
        self._pending_path_restore = False
        self._persist_last_path()
        self.reload()

    def _go_up(self) -> None:
        if len(self.crumbs) < 2:
            return
        self.crumbs.pop()
        self.current_path = self.crumbs[-1][1]
        self._pending_path_restore = False
        self._persist_last_path()
        self.reload()

    def _go_breadcrumb(self, index: int) -> None:
        trimmed = crumbs_after_navigate(self.crumbs, index)
        if trimmed is None:
            return
        self.crumbs = trimmed
        self.current_path = self.crumbs[-1][1]
        self._pending_path_restore = False
        self._persist_last_path()
        self.reload()

    def _clear_breadcrumb_box(self) -> None:
        child = self.breadcrumb_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.breadcrumb_box.remove(child)
            child = nxt

    def _rebuild_breadcrumbs(self) -> None:
        self._clear_breadcrumb_box()
        full_path = self.crumbs[-1][1] if self.crumbs else self.current_path
        self.breadcrumb_box.set_tooltip_text(full_path)
        last = len(self.crumbs) - 1
        for index, (label, path) in enumerate(self.crumbs):
            if index > 0:
                sep = Gtk.Label(label="›", css_classes=["dim-label"])
                sep.set_margin_start(2)
                sep.set_margin_end(2)
                self.breadcrumb_box.append(sep)
            if index == last:
                current = Gtk.Label(
                    label=label,
                    css_classes=["heading"],
                    ellipsize=Pango.EllipsizeMode.END,
                    max_width_chars=28,
                )
                current.set_tooltip_text(path)
                self.breadcrumb_box.append(current)
            else:
                btn = Gtk.Button(label=label, css_classes=["flat"])
                btn.set_tooltip_text(path)
                child = btn.get_child()
                if isinstance(child, Gtk.Label):
                    child.set_ellipsize(Pango.EllipsizeMode.END)
                    child.set_max_width_chars(22)
                btn.connect("clicked", lambda _b, idx=index: self._go_breadcrumb(idx))
                self.breadcrumb_box.append(btn)

    def open_section(self, path: str) -> None:
        index = 0
        row = self.side_list.get_row_at_index(0)
        while row is not None:
            if getattr(row, "path", None) == path:
                self.side_list.select_row(row)
                self._on_section(self.side_list, row)
                return
            index += 1
            row = self.side_list.get_row_at_index(index)

    def reload(self) -> None:
        path = self.current_path
        self._clear_search_query()
        self._set_busy(True, _("Reading {path}").format(path=path))
        self._rebuild_breadcrumbs()
        self.back_btn.set_sensitive(len(self.crumbs) > 1)
        in_trash = self.section == "/trash"
        in_photos = self.section == "/photos"
        if self.delete_permanently_btn is not None:
            self.delete_permanently_btn.set_visible(in_trash)
        if self.empty_trash_btn is not None:
            self.empty_trash_btn.set_visible(in_trash)
        if self.new_folder_btn is not None:
            self.new_folder_btn.set_tooltip_text(_("New album") if in_photos else _("New folder"))
        if self.copy_btn is not None:
            self.copy_btn.set_tooltip_text(_("Add to album") if in_photos else _("Copy"))
        if self.trash_btn is not None:
            if in_trash:
                self.trash_btn.set_tooltip_text(_("Restore"))
            elif in_photos:
                self.trash_btn.set_tooltip_text(_("Delete album or remove from album"))
            else:
                self.trash_btn.set_tooltip_text(_("Move to trash"))
        if self.section == "/photos":
            cache = self._timeline_cache
            self._bg(lambda: self._load_photos(path, cache), self._on_photos, self._on_nav_error)
            return
        self._bg(lambda: self._load_files(path), self._on_list, self._on_nav_error)

    def _load_photos(self, path: str, cache: list | None):
        timeline = cache if cache is not None else self.cli.photo_timeline()
        if path == "/photos":
            return {"kind": "root", "timeline": timeline, "albums": self.cli.album_list()}
        album_path = _photos_album_path(path)
        if album_path is not None:
            return {"kind": "album", "timeline": timeline, "photos": self.cli.album_photos(album_path)}
        day = _photos_day(path)
        if day is None:
            return {"kind": "root", "timeline": timeline, "albums": self.cli.album_list()}
        day_items = [item for item in timeline if str(item.get("captureTime") or "").startswith(day)]
        nodes = []
        enrich = len(day_items) <= 40
        for item in day_items:
            uid = str(item.get("nodeUid") or "")
            node = None
            if enrich and uid:
                try:
                    node = self.cli.info(f"/photos/{uid}")
                except CliError:
                    node = None
            if node is None:
                node = {
                    "type": "photo",
                    "name": _format_when(str(item.get("captureTime") or "")),
                    "uid": uid,
                    "modificationTime": item.get("captureTime"),
                    "photo": item,
                }
            nodes.append((node, uid))
        return {"kind": "day", "timeline": timeline, "nodes": nodes}

    def _on_photos(self, payload: dict) -> None:
        self._pending_path_restore = False
        self._set_busy(False)
        self.login_btn.set_visible(False)
        self.store.remove_all()
        timeline = payload.get("timeline") or []
        self._timeline_cache = timeline
        kind = payload.get("kind")
        if kind == "root":
            albums = payload.get("albums") or []
            for album in albums:
                name = node_name(album) if album.get("name") else str(album.get("path") or album.get("uid") or _("Album"))
                try:
                    album_path = album_cli_path(album)
                except CliError:
                    album_path = join_path("/albums", name)
                node = dict(album)
                node["type"] = "album"
                node["name"] = name
                self.store.append(DriveItem(node, album_path))
            days: dict[str, list] = {}
            for item in timeline:
                day = str(item.get("captureTime") or "")[:10] or "unknown"
                days.setdefault(day, []).append(item)
            for day in sorted(days, reverse=True):
                group = days[day]
                latest = group[0].get("captureTime") or ""
                node = {
                    "type": "day",
                    "name": _format_day(day),
                    "count": len(group),
                    "modificationTime": latest,
                }
                self.store.append(DriveItem(node, f"/photos/{day}"))
        elif kind == "album":
            for raw in payload.get("photos") or []:
                node = dict(raw)
                uid = str(node.get("uid") or node.get("nodeUid") or "")
                try:
                    photo_path = photo_cli_path(node)
                except CliError:
                    photo_path = f"/photos/{uid}" if uid else self.current_path
                if not node.get("name"):
                    capture = str(node.get("captureTime") or (node.get("photo") or {}).get("captureTime") or "")
                    node["name"] = _format_when(capture) if capture else (uid or _("Photo"))
                if not node.get("modificationTime"):
                    node["modificationTime"] = node.get("captureTime") or (node.get("photo") or {}).get("captureTime")
                node["type"] = "photo"
                self.store.append(DriveItem(node, photo_path))
        else:
            for node, uid in payload.get("nodes") or []:
                if node.get("type") != "photo":
                    node = dict(node)
                    node["type"] = "photo"
                capture = (node.get("photo") or {}).get("captureTime")
                if capture and not node.get("modificationTime"):
                    node = dict(node)
                    node["modificationTime"] = capture
                self.store.append(DriveItem(node, f"/photos/{uid}"))
        email = self.email
        for i in range(self.store.get_n_items()):
            item = self.store.get_item(i)
            if isinstance(item, DriveItem):
                found = account_email([item.node])
                if found:
                    email = found
                    break
        if email:
            self.email = email
        self.account_label.set_text(self.email or _("Signed in"))
        count = self.store.get_n_items()
        if count == 0:
            self.empty.set_title(_("No photos"))
            self.empty.set_description(_("Create an album from the toolbar, or photos appear from the official CLI timeline for this Proton account."))
            self.stack.set_visible_child_name("empty")
            self._listing_status_extra = ""
            self.status.set_text(_item_count(0))
            return
        self.empty.set_title(_("This folder is empty"))
        self.empty.set_description(_("Upload files with the official Proton Drive CLI session on this machine."))
        self.stack.set_visible_child_name("list")
        extra = ngettext("{count} photo", "{count} photos", len(timeline)).format(count=len(timeline)) if kind == "root" else (self.email or "Proton Drive")
        self._listing_status_extra = extra
        self._refresh_listing_status()

    def _load_files(self, path: str) -> tuple[list, list]:
        nodes = self.cli.list(path)
        invitations: list = []
        if path.rstrip("/") == "/shared-with-me":
            invitations = self.cli.invitation_list()
        return nodes, invitations

    def _on_list(self, payload) -> None:
        self._pending_path_restore = False
        self._set_busy(False)
        self.login_btn.set_visible(False)
        self.store.remove_all()
        if isinstance(payload, tuple):
            nodes, invitations = payload
        else:
            nodes, invitations = payload, []
        email = account_email(nodes)
        if email:
            self.email = email
        self.account_label.set_text(self.email or _("Signed in"))
        for invite in invitations:
            uid = invitation_uid(invite)
            node = dict(invite)
            node["type"] = "invitation"
            node["name"] = invitation_name(invite)
            node["modificationTime"] = invite.get("invitationTime") or invite.get("creationTime") or ""
            self.store.append(DriveItem(node, f"/invitations/{uid}" if uid else "/invitations"))
        folders = [n for n in nodes if n.get("type") == "folder"]
        files = [n for n in nodes if n.get("type") != "folder"]
        for node in folders + files:
            self.store.append(DriveItem(node, join_path(self.current_path, node_name(node))))
        count = self.store.get_n_items()
        if count == 0:
            if self.section == "/shared-with-me":
                self.empty.set_title(_("Nothing shared with you"))
                self.empty.set_description(_("Pending invitations from proton-drive invitation list appear here. Share your own files from My files."))
            elif self.section == "/trash":
                self.empty.set_title(_("Trash is empty"))
                self.empty.set_description(_("Trashed files appear here. Delete permanently removes one selected item. Empty trash permanently deletes everything in /trash."))
            else:
                self.empty.set_title(_("This folder is empty"))
                self.empty.set_description(_("Upload files with the official Proton Drive CLI session on this machine."))
            self.stack.set_visible_child_name("empty")
            self._listing_status_extra = ""
            self.status.set_text(_item_count(0))
            return
        self.empty.set_title(_("This folder is empty"))
        self.empty.set_description(_("Upload files with the official Proton Drive CLI session on this machine."))
        self.stack.set_visible_child_name("list")
        pending = ""
        if invitations:
            pending = _(" · {count} invitation(s)").format(count=len(invitations))
        self._listing_status_extra = f"{self.email or 'Proton Drive'}{pending}"
        self._refresh_listing_status()

    def _filter_item(self, item: GObject.Object) -> bool:
        if not isinstance(item, DriveItem):
            return False
        return listing_name_matches(item.name, self._search_query)

    def _refresh_listing_status(self) -> None:
        total = self.store.get_n_items()
        shown = self.filtered_store.get_n_items()
        if self._search_query.strip() and shown != total:
            count_text = _("{shown} of {total}").format(shown=_item_count(shown), total=_item_count(total))
        else:
            count_text = _item_count(total)
        extra = self._listing_status_extra
        if extra:
            self.status.set_text(_("{count} · {extra}").format(count=count_text, extra=extra))
        else:
            self.status.set_text(count_text)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_query = entry.get_text() or ""
        self.name_filter.changed(Gtk.FilterChange.DIFFERENT)
        if self.store.get_n_items() > 0:
            self.stack.set_visible_child_name("list")
            self._refresh_listing_status()

    def _on_stop_search(self, *_args) -> None:
        self.search_bar.set_search_mode(False)
        if self.search_entry.get_text():
            self.search_entry.set_text("")

    def _toggle_search(self, *_args) -> None:
        enabled = not self.search_bar.get_search_mode()
        self.search_bar.set_search_mode(enabled)
        if enabled:
            self.search_entry.grab_focus()

    def _clear_search_query(self) -> None:
        if self._search_query or (hasattr(self, "search_entry") and self.search_entry.get_text()):
            self._search_query = ""
            if hasattr(self, "search_entry"):
                self.search_entry.set_text("")
            if hasattr(self, "name_filter"):
                self.name_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _selected_items(self) -> list[DriveItem]:
        items: list[DriveItem] = []
        for i in range(self.selection.get_n_items()):
            if not self.selection.is_selected(i):
                continue
            item = self.selection.get_item(i)
            if isinstance(item, DriveItem):
                items.append(item)
        return items

    def _selected(self) -> DriveItem | None:
        items = self._selected_items()
        return items[0] if items else None

    def _selected_position(self, item: DriveItem) -> int:
        for i in range(self.selection.get_n_items()):
            if self.selection.get_item(i) is item:
                return i
        return -1

    def _open_selected(self, *_args) -> None:
        items = self._selected_items()
        if not items:
            return
        if len(items) > 1:
            self._toast(_("Open one item at a time"))
            return
        position = self._selected_position(items[0])
        if position >= 0:
            self._on_activate(self._active_files_view(), position)

    def _on_key(self, _controller, keyval, _keycode, state) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            self.selection.select_all()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._open_selected()
            return True
        if keyval == Gdk.KEY_F2:
            self._rename()
            return True
        if keyval == Gdk.KEY_Escape and self.search_bar.get_search_mode():
            self._on_stop_search()
            return True
        return False

    def _on_item_context(self, _gesture, _n_press, x, y) -> None:
        items = self._selected_items()
        if not items:
            self._toast(_("Select an item first"))
            return
        if self._item_popover is not None:
            self._item_popover.popdown()
            self._item_popover.unparent()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        if len(items) > 1:
            if self.section == "/trash":
                actions = [(_("Restore"), self._trash)]
            elif self.section == "/photos":
                if _photos_album_path(self.current_path) and all(i.kind == "photo" for i in items):
                    actions = [(_("Remove from album"), self._trash), (_("Download"), self._download)]
                elif all(is_downloadable_kind(i.kind) for i in items):
                    actions = [(_("Download"), self._download)]
                else:
                    actions = [(_("Download"), self._download)]
            else:
                actions = [
                    (_("Download"), self._download),
                    (_("Move"), self._move),
                    (_("Move to trash"), self._trash),
                ]
        elif self.section == "/trash":
            actions = [
                (_("Restore"), self._trash),
                (_("Delete permanently"), self._delete_permanently),
                (_("Empty trash"), self._empty_trash),
            ]
        elif self.section == "/photos":
            item = items[0]
            if item.kind == "album":
                actions = [(_("Rename"), self._rename), (_("Delete album"), self._delete_album)]
            elif item.kind == "photo" and _photos_album_path(self.current_path):
                actions = [(_("Add to album"), self._add_to_album), (_("Remove from album"), self._remove_from_album)]
            elif item.kind == "photo":
                actions = [(_("Add to album"), self._add_to_album)]
            else:
                actions = [(_("Open"), self._open_selected)]
        else:
            actions = [(_("Rename"), self._rename), (_("Copy"), self._copy), (_("Move"), self._move)]
        if len(items) == 1:
            actions = list(actions) + [(_("Properties"), self._properties)]
        popover = Gtk.Popover()
        for label, handler in actions:
            btn = Gtk.Button(label=label, has_frame=False)
            child = btn.get_child()
            if isinstance(child, Gtk.Label):
                child.set_xalign(0)
            btn.connect("clicked", lambda _b, h=handler, p=popover: (p.popdown(), h()))
            box.append(btn)
        popover.set_child(box)
        popover.set_parent(self._active_files_view())
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        self._item_popover = popover
        popover.popup()

    def _on_activate(self, _view, position: int) -> None:
        item = self.selection.get_item(position) if position >= 0 else None
        if not isinstance(item, DriveItem):
            return
        if item.kind in ("folder", "day", "album"):
            self.crumbs.append((item.name, item.path))
            self.current_path = item.path
            self._pending_path_restore = False
            self._persist_last_path()
            self.reload()
        elif item.kind == "invitation":
            InvitationDialog(self, item).present()
        else:
            self._download_item(item)

    def _login(self, *_args) -> None:
        self._toast(_("Complete Proton sign-in in the browser, then this window will refresh."))
        self._bg(self.cli.login, lambda *_: self.reload(), self._fail)

    def _new_folder(self, *_args) -> None:
        if self.section == "/photos":
            dialog = Adw.MessageDialog(transient_for=self, heading=_("New album"), body=_("Album name. Uses proton-drive album create."))
            entry = Gtk.Entry(placeholder_text=_("Name"))
            dialog.set_extra_child(entry)
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("create", _("Create"))
            dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", self._on_new_album, entry)
            dialog.present()
            return
        dialog = Adw.MessageDialog(transient_for=self, heading=_("New folder"), body=_("Folder name"))
        entry = Gtk.Entry(placeholder_text=_("Name"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_new_folder, entry)
        dialog.present()

    def _on_new_folder(self, dialog, response: str, entry: Gtk.Entry) -> None:
        if response != "create":
            return
        name = entry.get_text().strip()
        if not name:
            return
        parent = self.current_path
        self._bg(lambda: self.cli.mkdir(parent, name), lambda *_: self.reload())

    def _on_new_album(self, _dialog, response: str, entry: Gtk.Entry) -> None:
        if response != "create":
            return
        name = entry.get_text().strip()
        if not name:
            self._toast(_("Enter a name"))
            return
        self._bg(lambda: self.cli.album_create(name), lambda *_: (self._toast(_("Created album {name}").format(name=name)), self.reload()), self._mutate_error)

    def _upload(self, *_args) -> None:
        dialog = Gtk.FileDialog(title=_("Upload to Proton Drive"))
        dialog.open_multiple(self, None, self._on_upload_chosen)

    def _on_upload_chosen(self, dialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        if files is None:
            return
        paths = []
        for i in range(files.get_n_items()):
            file = files.get_item(i)
            if isinstance(file, Gio.File) and file.get_path():
                paths.append(file.get_path())
        self._start_upload(paths)

    def _on_files_dropped(self, _target, value, _x, _y) -> bool:
        if self.section != "/my-files":
            self._toast(_("Drag and drop uploads only in My files"))
            return False
        if not isinstance(value, Gdk.FileList):
            return False
        paths = []
        for file in value.get_files():
            path = file.get_path() if isinstance(file, Gio.File) else None
            if path:
                paths.append(path)
        if not paths:
            return False
        self._start_upload(paths)
        return True

    def _start_upload(self, paths: list[str]) -> None:
        if not paths:
            return
        parent = self.current_path
        label = ngettext("Uploading {count} item", "Uploading {count} items", len(paths)).format(count=len(paths))
        photos = self.section == "/photos"

        def runner(on_progress):
            if photos:
                self.cli.photo_upload(paths, on_progress=on_progress)
            else:
                self.cli.upload(paths, parent, on_progress=on_progress)
            return None

        self._enqueue_transfer("photo_upload" if photos else "upload", label, runner)

    def _download(self, *_args) -> None:
        items = self._selected_items()
        if not items:
            self._toast(_("Select a file or folder first"))
            return
        downloadable = [item for item in items if is_downloadable_kind(item.kind)]
        if not downloadable:
            if len(items) == 1:
                self._download_item(items[0])
                return
            self._toast(_("Select files or folders to download"))
            return
        if len(downloadable) == 1:
            self._download_item(downloadable[0])
            return
        dest = str(download_folder())
        label = ngettext("Downloading {count} item", "Downloading {count} items", len(downloadable)).format(
            count=len(downloadable)
        )
        photo = self.section == "/photos" or all(item.kind == "photo" for item in downloadable)
        remotes = [item.path for item in downloadable]

        def runner(on_progress):
            for remote in remotes:
                if photo:
                    self.cli.photo_download(remote, dest, on_progress=on_progress)
                else:
                    self.cli.download(remote, dest, on_progress=on_progress)
            return dest

        self._enqueue_transfer("photo_download" if photo else "download", label, runner)

    def _download_item(self, item: DriveItem) -> None:
        if item.kind in ("day", "album"):
            self._toast(_("Open a day or album, then select a photo"))
            return
        if item.kind == "invitation":
            InvitationDialog(self, item).present()
            return
        dest = str(download_folder())
        label = _("Downloading {name}").format(name=item.name)
        photo = item.kind == "photo" or self.section == "/photos"
        remote = item.path

        def runner(on_progress):
            if photo:
                self.cli.photo_download(remote, dest, on_progress=on_progress)
            else:
                self.cli.download(remote, dest, on_progress=on_progress)
            return dest

        self._enqueue_transfer("photo_download" if photo else "download", label, runner)

    def _trash(self, *_args) -> None:
        items = self._selected_items()
        if not items:
            self._toast(_("Select an item first"))
            return
        if len(items) == 1:
            self._trash_one(items[0])
            return
        self._trash_many(items)

    def _trash_one(self, item: DriveItem) -> None:
        if item.kind == "invitation":
            InvitationDialog(self, item).present()
            return
        if self.section == "/trash":
            self._bg(lambda: self.cli.restore(item.path), lambda *_: (self._toast(_("Restored")), self.reload()))
            return
        if self.section == "/photos":
            if item.kind == "album":
                self._delete_album()
                return
            if item.kind == "photo" and _photos_album_path(self.current_path):
                self._remove_from_album()
                return
            self._toast(_("Photos stay in the timeline. Delete an album, or open an album to remove a photo from it."))
            return
        self._bg(lambda: self.cli.trash(item.path), lambda *_: (self._toast(_("Moved to trash")), self.reload()))

    def _trash_many(self, items: list[DriveItem]) -> None:
        if self.section == "/trash":
            paths = [item.path for item in items if item.kind != "invitation"]
            if not paths:
                self._toast(_("Select items in Trash first"))
                return
            count = len(paths)

            def work():
                for path in paths:
                    self.cli.restore(path)

            self._set_busy(True, ngettext("Restoring {count} item", "Restoring {count} items", count).format(count=count))
            self._bg(
                work,
                lambda *_: (
                    self._toast(ngettext("Restored {count} item", "Restored {count} items", count).format(count=count)),
                    self.reload(),
                ),
                self._mutate_error,
            )
            return
        if self.section == "/photos":
            album_path = _photos_album_path(self.current_path)
            photos = [item for item in items if item.kind == "photo"]
            if album_path and photos and len(photos) == len(items):
                photo_paths = [item.path for item in photos]
                count = len(photo_paths)
                self._set_busy(
                    True,
                    ngettext("Removing {count} photo", "Removing {count} photos", count).format(count=count),
                )
                self._bg(
                    lambda: self.cli.album_remove_photo(album_path, photo_paths),
                    lambda *_: (
                        self._toast(
                            ngettext("Removed {count} photo from album", "Removed {count} photos from album", count).format(
                                count=count
                            )
                        ),
                        self.reload(),
                    ),
                    self._mutate_error,
                )
                return
            downloadable = [item for item in items if is_downloadable_kind(item.kind)]
            if downloadable:
                self._toast(_("Photos stay in the timeline. Open an album to remove photos, or download the selection."))
                return
            self._toast(_("Photos stay in the timeline. Delete an album, or open an album to remove a photo from it."))
            return
        paths = [item.path for item in items if item.kind != "invitation"]
        if not paths:
            self._toast(_("Select an item first"))
            return
        count = len(paths)

        def work():
            for path in paths:
                self.cli.trash(path)

        self._set_busy(True, ngettext("Moving {count} item to trash", "Moving {count} items to trash", count).format(count=count))
        self._bg(
            work,
            lambda *_: (
                self._toast(ngettext("Moved {count} item to trash", "Moved {count} items to trash", count).format(count=count)),
                self.reload(),
            ),
            self._mutate_error,
        )

    def _mutate_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._toast(str(exc)[:180])

    def _file_op_items(self) -> list[DriveItem]:
        items = self._selected_items()
        if not items:
            self._toast(_("Select a file or folder first"))
            return []
        usable = [item for item in items if is_movable_item(item.kind, item.path, self.section)]
        if not usable:
            if any(item.path.startswith("/trash") or self.section == "/trash" for item in items):
                self._toast(_("Restore the item from Trash first"))
            else:
                self._toast(_("Select a file or folder first"))
            return []
        return usable

    def _file_op_item(self) -> DriveItem | None:
        items = self._selected_items()
        if not items:
            self._toast(_("Select a file or folder first"))
            return None
        if len(items) > 1:
            self._toast(_("Select a single file or folder"))
            return None
        item = items[0]
        if item.kind in ("invitation", "day", "album"):
            self._toast(_("Select a file or folder first"))
            return None
        if self.section == "/trash" or item.path.startswith("/trash"):
            self._toast(_("Restore the item from Trash first"))
            return None
        if item.path in _UNSHAREABLE_ROOTS:
            self._toast(_("Select a file or folder first"))
            return None
        return item

    def _properties(self, *_args) -> None:
        items = self._selected_items()
        if not items:
            self._toast(_("Select an item first"))
            return
        if len(items) > 1:
            self._toast(_("Select a single item"))
            return
        PropertiesDialog(self, items[0]).present(self)

    def _default_dest(self) -> str:
        if self.section in ("/trash", "/photos") or self.current_path in _UNSHAREABLE_ROOTS:
            return "/my-files"
        if self.current_path.startswith("/photos"):
            return "/my-files"
        return self.current_path

    def _rename(self, *_args) -> None:
        item = self._selected()
        if item is not None and item.kind == "album":
            dialog = Adw.MessageDialog(transient_for=self, heading=_("Rename album"), body=item.path)
            entry = Gtk.Entry()
            entry.set_text(item.name)
            entry.set_placeholder_text(_("New name"))
            dialog.set_extra_child(entry)
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("rename", _("Rename"))
            dialog.set_default_response("rename")
            dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", self._on_rename_album, item, entry)
            dialog.present()
            return
        item = self._file_op_item()
        if item is None:
            return
        dialog = Adw.MessageDialog(transient_for=self, heading=_("Rename"), body=item.path)
        entry = Gtk.Entry()
        entry.set_text(item.name)
        entry.set_placeholder_text(_("New name"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("rename", _("Rename"))
        dialog.set_default_response("rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_rename, item, entry)
        dialog.present()

    def _on_rename(self, _dialog, response: str, item: DriveItem, entry: Gtk.Entry) -> None:
        if response != "rename":
            return
        name = entry.get_text().strip()
        if not name:
            self._toast(_("Enter a name"))
            return
        if name == item.name:
            return
        path = item.path
        self._bg(lambda: self.cli.rename(path, name), lambda *_: (self._toast(_("Renamed to {name}").format(name=name)), self.reload()), self._mutate_error)

    def _on_rename_album(self, _dialog, response: str, item: DriveItem, entry: Gtk.Entry) -> None:
        if response != "rename":
            return
        name = entry.get_text().strip()
        if not name:
            self._toast(_("Enter a name"))
            return
        if name == item.name:
            return
        path = item.path

        def done(_result) -> None:
            new_path = join_path("/albums", name)
            if self.current_path == path:
                self.current_path = new_path
                self.crumbs[-1] = (name, new_path)
                self._persist_last_path()
            self._toast(_("Renamed to {name}").format(name=name))
            self.reload()

        self._bg(lambda: self.cli.album_update(path, name=name), done, self._mutate_error)

    def _add_to_album(self, *_args) -> None:
        item = self._selected()
        if item is None or item.kind != "photo":
            self._toast(_("Select a photo to add to an album"))
            return
        AlbumPickerDialog(self, item).present(self)

    def _remove_from_album(self, *_args) -> None:
        item = self._selected()
        album_path = _photos_album_path(self.current_path)
        if item is None or item.kind != "photo" or album_path is None:
            self._toast(_("Open an album, then select a photo to remove"))
            return
        photo_path = item.path
        self._bg(
            lambda: self.cli.album_remove_photo(album_path, [photo_path]),
            lambda *_: (self._toast(_("Removed from album")), self.reload()),
            self._mutate_error,
        )

    def _delete_album(self, *_args) -> None:
        item = self._selected()
        if item is None or item.kind != "album":
            self._toast(_("Select an album first"))
            return
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Delete album?"),
            body=_("Deletes “{name}”. Photos stay in your Photos timeline. This cannot be undone.").format(name=item.name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete album"))
        dialog.set_default_response("cancel")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_album, item)
        dialog.present()

    def _on_delete_album(self, _dialog, response: str, item: DriveItem) -> None:
        if response != "delete":
            return
        path = item.path

        def done(_result) -> None:
            self._toast(_("Album deleted"))
            if self.current_path == path:
                self._go_up()
                return
            self.reload()

        self._bg(lambda: self.cli.album_delete(path, save=True), done, self._mutate_error)

    def _copy(self, *_args) -> None:
        if self.section == "/photos":
            self._add_to_album()
            return
        item = self._file_op_item()
        if item is None:
            return
        DestinationDialog(self, item, "copy").present(self)

    def _move(self, *_args) -> None:
        if self.section == "/photos":
            self._toast(_("Move is for files in My files. Add a photo to an album instead."))
            return
        items = self._file_op_items()
        if not items:
            return
        DestinationDialog(self, items, "move").present(self)

    def _delete_permanently(self, *_args) -> None:
        if self.section != "/trash":
            self._toast(_("Open Trash to delete an item permanently"))
            return
        item = self._selected()
        if item is None:
            self._toast(_("Select an item in Trash first"))
            return
        if item.kind == "invitation":
            self._toast(_("Select a file or folder in Trash"))
            return
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Delete permanently?"),
            body=_("Permanently deletes “{name}” from Trash. Other items stay in Trash. This cannot be undone.").format(name=item.name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete permanently"))
        dialog.set_default_response("cancel")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_permanently, item)
        dialog.present()

    def _on_delete_permanently(self, _dialog, response: str, item: DriveItem) -> None:
        if response != "delete":
            return
        path = item.path
        name = item.name
        self._set_busy(True, _("Deleting {name}").format(name=name))
        self._bg(
            lambda: self.cli.delete(path),
            lambda *_: (self._toast(_("Permanently deleted {name}").format(name=name)), self.reload()),
            self._mutate_error,
        )

    def _empty_trash(self, *_args) -> None:
        if self.section != "/trash":
            self._toast(_("Open Trash to empty it"))
            return
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=_("Empty trash?"),
            body=_("Permanently deletes every item in Trash. Photos trash is not affected. This cannot be undone."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("empty", _("Empty trash"))
        dialog.set_default_response("cancel")
        dialog.set_response_appearance("empty", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_empty_trash)
        dialog.present()

    def _on_empty_trash(self, _dialog, response: str) -> None:
        if response != "empty":
            return
        self._set_busy(True, _("Emptying trash"))
        self._bg(self.cli.empty_trash, lambda *_: (self._toast(_("Trash emptied")), self.reload()), self._mutate_error)

    def _share(self, *_args) -> None:
        item = self._selected()
        if item is not None and item.kind == "invitation":
            InvitationDialog(self, item).present()
            return
        if item is None:
            if self.current_path in _UNSHAREABLE_ROOTS or _photos_day(self.current_path):
                if self.section == "/shared-with-me":
                    self._toast(_("Select a shared item, or open Shared with me to see pending invitations"))
                else:
                    self._toast(_("Select a file or folder to share"))
                return
            item = DriveItem({"type": "folder", "name": self.crumbs[-1][0]}, self.current_path)
        if item.kind in ("day", "album"):
            self._toast(_("Open a day or album, then share a photo"))
            return
        if item.path in _UNSHAREABLE_ROOTS or item.path.startswith("/trash"):
            self._toast(_("Select a file or folder inside My files to share"))
            return
        ShareDialog(self, item).present(self)

    def _share_error(self, exc: BaseException) -> None:
        self._toast(str(exc)[:180])


class DestinationDialog(Adw.Dialog):
    def __init__(self, window: DriveWindow, item_or_items: DriveItem | list[DriveItem], action: str) -> None:
        super().__init__()
        self.window = window
        if isinstance(item_or_items, DriveItem):
            self.items = [item_or_items]
        else:
            self.items = list(item_or_items)
        self.item = self.items[0]
        self.action = action
        self.dest_path = window._default_dest()
        verb = _("Copy") if action == "copy" else _("Move")
        if len(self.items) == 1:
            self.set_title(_("{verb} {name}").format(verb=verb, name=self.item.name))
            summary = _("{verb} \"{name}\" into a folder. Click a folder to open it.").format(verb=verb, name=self.item.name)
        else:
            count = len(self.items)
            self.set_title(ngettext("{verb} {count} item", "{verb} {count} items", count).format(verb=verb, count=count))
            summary = ngettext(
                "{verb} {count} item into a folder. Click a folder to open it.",
                "{verb} {count} items into a folder. Click a folder to open it.",
                count,
            ).format(verb=verb, count=count)
        self.set_content_width(480)
        self.set_content_height(520)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.path_title = Adw.WindowTitle(title=verb, subtitle=self.dest_path)
        header.set_title_widget(self.path_title)
        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=_("Back"))
        self.back_btn.connect("clicked", lambda *_: self._go_up())
        header.pack_start(self.back_btn)
        toolbar.add_top_bar(header)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=16, margin_end=16, margin_top=8, margin_bottom=16)
        page.append(Gtk.Label(label=summary, xalign=0, wrap=True, css_classes=["dim-label"]))
        roots = Gtk.DropDown.new_from_strings([_("My files"), _("Shared with me")])
        roots.set_selected(0)
        roots.connect("notify::selected", self._on_root)
        page.append(roots)
        self.root_drop = roots
        if action == "copy" and len(self.items) == 1:
            self.name_entry = Gtk.Entry(text=self.item.name, placeholder_text=_("Name of the copy"))
            page.append(self.name_entry)
        else:
            self.name_entry = None
        scrolled = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.folders = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
        self.folders.connect("row-activated", self._on_folder)
        scrolled.set_child(self.folders)
        page.append(scrolled)
        empty_text = _("No folders here. Use the button to copy into this location.") if action == "copy" else _("No folders here. Use the button to move into this location.")
        self.empty = Gtk.Label(label=empty_text, xalign=0, wrap=True, css_classes=["dim-label"])
        page.append(self.empty)
        confirm = Gtk.Button(label=_("{verb} here").format(verb=verb), css_classes=["suggested-action"], halign=Gtk.Align.START)
        confirm.connect("clicked", self._confirm)
        page.append(confirm)
        toolbar.set_content(page)
        self.set_child(toolbar)
        self._load(self.dest_path)

    def _on_root(self, drop, _pspec) -> None:
        selected = int(drop.get_selected())
        path = "/shared-with-me" if selected == 1 else "/my-files"
        self._load(path)

    def _go_up(self) -> None:
        if self.dest_path in ("/my-files", "/shared-with-me"):
            return
        parent = self.dest_path.rsplit("/", 1)[0] or "/my-files"
        if not parent.startswith("/"):
            parent = "/my-files"
        self._load(parent)

    def _load(self, path: str) -> None:
        self.dest_path = path
        self.path_title.set_subtitle(path)
        self.back_btn.set_sensitive(path not in ("/my-files", "/shared-with-me"))
        self.window._bg(lambda: self.window.cli.list(path), self._on_list, self.window._mutate_error)

    def _on_list(self, nodes) -> None:
        child = self.folders.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.folders.remove(child)
            child = nxt
        folders = [n for n in (nodes or []) if isinstance(n, dict) and n.get("type") == "folder"]
        self.empty.set_visible(not folders)
        selected_paths = {item.path for item in self.items}
        for node in folders:
            name = node_name(node)
            path = join_path(self.dest_path, name)
            if path in selected_paths:
                continue
            row = Gtk.ListBoxRow()
            row.dest_path = path  # type: ignore[attr-defined]
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
            box.append(Gtk.Image.new_from_icon_name("folder-symbolic"))
            box.append(Gtk.Label(label=name, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
            row.set_child(box)
            self.folders.append(row)

    def _on_folder(self, _list, row) -> None:
        path = getattr(row, "dest_path", None)
        if path:
            self._load(path)

    def _confirm(self, *_args) -> None:
        dest = self.dest_path
        sources = [item for item in self.items if not dest_is_inside_source(dest, item.path)]
        if not sources:
            self.window._toast(_("Choose a different folder"))
            return
        name = None
        if self.name_entry is not None:
            name = self.name_entry.get_text().strip() or None
            if name == self.item.name:
                name = None
        window = self.window
        action = self.action
        count = len(sources)
        self.close()

        def work():
            for item in sources:
                if action == "copy":
                    window.cli.copy(item.path, dest, name=name if count == 1 else None)
                else:
                    window.cli.move(item.path, dest)

        def done(_result) -> None:
            if action == "copy":
                verb = _("Copied")
                toast = (
                    _("{verb} to {dest}").format(verb=verb, dest=dest)
                    if count == 1
                    else ngettext("Copied {count} item to {dest}", "Copied {count} items to {dest}", count).format(
                        count=count, dest=dest
                    )
                )
            else:
                toast = (
                    _("Moved to {dest}").format(dest=dest)
                    if count == 1
                    else ngettext("Moved {count} item to {dest}", "Moved {count} items to {dest}", count).format(
                        count=count, dest=dest
                    )
                )
            window._toast(toast)
            window.reload()

        if action == "copy":
            busy = (
                _("Copying {name}").format(name=self.item.name)
                if count == 1
                else ngettext("Copying {count} item", "Copying {count} items", count).format(count=count)
            )
        else:
            busy = (
                _("Moving {name}").format(name=self.item.name)
                if count == 1
                else ngettext("Moving {count} item", "Moving {count} items", count).format(count=count)
            )
        window._set_busy(True, busy)
        window._bg(work, done, window._mutate_error)


class AlbumPickerDialog(Adw.Dialog):
    def __init__(self, window: DriveWindow, photo: DriveItem) -> None:
        super().__init__()
        self.window = window
        self.photo = photo
        self.set_title(_("Add to album"))
        self.set_content_width(420)
        self.set_content_height(420)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=_("Add to album"), subtitle=photo.name))
        toolbar.add_top_bar(header)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=16, margin_end=16, margin_top=8, margin_bottom=16)
        page.append(Gtk.Label(label=_("Choose an album. Uses proton-drive album add-photo with the live photo UID."), xalign=0, wrap=True, css_classes=["dim-label"]))
        scrolled = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.albums = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
        self.albums.connect("row-activated", self._on_album)
        scrolled.set_child(self.albums)
        page.append(scrolled)
        self.empty = Gtk.Label(label=_("No albums yet. Create one from Photos with New album."), xalign=0, wrap=True, css_classes=["dim-label"])
        page.append(self.empty)
        toolbar.set_content(page)
        self.set_child(toolbar)
        window._bg(window.cli.album_list, self._on_list, window._mutate_error)

    def _on_list(self, nodes) -> None:
        child = self.albums.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.albums.remove(child)
            child = nxt
        albums = [n for n in (nodes or []) if isinstance(n, dict)]
        self.empty.set_visible(not albums)
        for node in albums:
            name = node_name(node) if node.get("name") else str(node.get("uid") or _("Album"))
            try:
                path = album_cli_path(node)
            except CliError:
                path = join_path("/albums", name)
            row = Gtk.ListBoxRow()
            row.album_path = path  # type: ignore[attr-defined]
            row.album_name = name  # type: ignore[attr-defined]
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
            box.append(Gtk.Image.new_from_icon_name("folder-pictures-symbolic"))
            box.append(Gtk.Label(label=name, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
            row.set_child(box)
            self.albums.append(row)

    def _on_album(self, _list, row) -> None:
        album_path = getattr(row, "album_path", None)
        album_name = getattr(row, "album_name", "album")
        if not album_path:
            return
        photo_path = self.photo.path
        window = self.window
        self.close()

        def work():
            return window.cli.album_add_photo(album_path, [photo_path])

        def done(_result) -> None:
            window._toast(_("Added to {album}").format(album=album_name))
            window.reload()

        window._bg(work, done, window._mutate_error)


class PropertiesDialog(Adw.Dialog):
    """Read-only listing metadata: name, type, size, modified, share status, path."""

    def __init__(self, window: DriveWindow, item: DriveItem) -> None:
        super().__init__()
        self.set_title(_("Properties"))
        self.set_content_width(460)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=_("Properties"), subtitle=item.name))
        toolbar.add_top_bar(header)

        group = Adw.PreferencesGroup()
        rows = item_property_rows(
            name=item.name,
            kind=item.kind,
            size=item.size,
            modified=item.modified,
            path=item.path,
            is_shared=bool(item.node.get("isShared")),
            is_shared_by_url=bool(item.node.get("isSharedByUrl")),
        )
        for title, value in rows:
            row = Adw.ActionRow(title=title, subtitle=value)
            row.add_css_class("property")
            row.set_subtitle_selectable(True)
            group.add(row)

        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=16,
            margin_end=16,
            margin_top=8,
            margin_bottom=16,
        )
        page.append(group)
        toolbar.set_content(page)
        self.set_child(toolbar)


class InvitationDialog(Adw.MessageDialog):
    def __init__(self, window: DriveWindow, item: DriveItem) -> None:
        uid = invitation_uid(item.node)
        inviter = added_by_email(item.node) or _("Someone")
        role = member_role(item.node)
        super().__init__(
            transient_for=window,
            heading=item.name,
            body=_("{inviter} invited you as {role}. Accept or reject uses the official CLI invitation UID.").format(inviter=inviter, role=role),
        )
        self.window = window
        self.uid = uid
        self.add_response("cancel", _("Cancel"))
        self.add_response("reject", _("Reject"))
        self.add_response("accept", _("Accept"))
        self.set_response_appearance("reject", Adw.ResponseAppearance.DESTRUCTIVE)
        self.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self._on_response)

    def _on_response(self, _dialog, response: str) -> None:
        if response not in ("accept", "reject") or not self.uid:
            if response in ("accept", "reject") and not self.uid:
                self.window._toast(_("Invitation has no UID from proton-drive invitation list"))
            return
        cli = self.window.cli
        uid = self.uid

        def work():
            if response == "accept":
                cli.invitation_accept(uid)
            else:
                cli.invitation_reject(uid)
            return response

        def done(action: str) -> None:
            self.window._toast(_("Invitation accepted") if action == "accept" else _("Invitation rejected"))
            self.window.reload()

        self.window._bg(work, done, self.window._share_error)


class ShareDialog(Adw.Dialog):
    def __init__(self, window: DriveWindow, item: DriveItem) -> None:
        super().__init__()
        self.window = window
        self.item = item
        self.status: dict = {}
        self.set_title(_("Share {name}").format(name=item.name))
        self.set_content_width(520)
        self.set_content_height(620)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=_("Share"), subtitle=item.path))
        toolbar.add_top_bar(header)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_start=16, margin_end=16, margin_top=8, margin_bottom=16)
        scrolled = Gtk.ScrolledWindow(hexpand=True, vexpand=True, propagate_natural_height=True)
        scrolled.set_child(page)
        toolbar.set_content(scrolled)
        self.set_child(toolbar)

        invite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        invite.append(Gtk.Label(label=_("Invite people"), xalign=0, css_classes=["heading"]))
        self.email = Gtk.Entry(placeholder_text=_("Email address"))
        self.email.connect("activate", self._invite)
        invite.append(self.email)
        self.role = Gtk.DropDown.new_from_strings(list(_INVITE_ROLES))
        self.role.set_selected(0)
        invite.append(self.role)
        self.message = Gtk.Entry(placeholder_text=_("Optional message in the invitation email"))
        invite.append(self.message)
        self.include_name = Gtk.CheckButton(label=_("Include the file name in the email (clear text)"))
        invite.append(self.include_name)
        send = Gtk.Button(label=_("Send invitation"), css_classes=["suggested-action"], halign=Gtk.Align.START)
        send.connect("clicked", self._invite)
        invite.append(send)
        page.append(invite)

        people = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        people.append(Gtk.Label(label=_("People with access"), xalign=0, css_classes=["heading"]))
        self.people = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        people.append(self.people)
        self.people_empty = Gtk.Label(label=_("Not shared yet"), xalign=0, css_classes=["dim-label"])
        people.append(self.people_empty)
        page.append(people)

        link = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        link.append(Gtk.Label(label=_("Public link"), xalign=0, css_classes=["heading"]))
        self.link_label = Gtk.Label(label=_("No public link"), xalign=0, wrap=True, selectable=True)
        link.append(self.link_label)
        self.link_role = Gtk.DropDown.new_from_strings(list(_LINK_ROLES))
        self.link_role.set_selected(0)
        link.append(self.link_role)
        self.link_password = Gtk.PasswordEntry(placeholder_text=_("Optional link password"), show_peek_icon=True)
        link.append(self.link_password)
        self.link_expiration = Gtk.Entry(placeholder_text=_("Optional expiration (YYYY-MM-DD)"))
        link.append(self.link_expiration)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.link_create = Gtk.Button(label=_("Create or update link"))
        self.link_create.connect("clicked", self._set_url)
        self.link_copy = Gtk.Button(label=_("Copy link"))
        self.link_copy.connect("clicked", self._copy_url)
        self.link_remove = Gtk.Button(label=_("Remove link"), css_classes=["destructive-action"])
        self.link_remove.connect("clicked", self._remove_url)
        buttons.append(self.link_create)
        buttons.append(self.link_copy)
        buttons.append(self.link_remove)
        link.append(buttons)
        page.append(link)

        danger = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if window.section == "/shared-with-me":
            leave = Gtk.Button(label=_("Leave share"), css_classes=["destructive-action"])
            leave.connect("clicked", self._leave)
            danger.append(leave)
        else:
            stop = Gtk.Button(label=_("Stop sharing"), css_classes=["destructive-action"])
            stop.connect("clicked", self._stop)
            danger.append(stop)
        page.append(danger)

        window._bg(lambda: window.cli.sharing_status(item.path), self._on_status, window._share_error)

    def _on_status(self, status) -> None:
        self.status = status if isinstance(status, dict) else {}
        self._render_people()
        self._render_link()

    def _people_rows(self) -> list[tuple[dict, str]]:
        rows: list[tuple[dict, str]] = []
        for item in self.status.get("protonInvitations") or []:
            if isinstance(item, dict):
                rows.append((item, _("Pending invitation")))
        for item in self.status.get("nonProtonInvitations") or []:
            if isinstance(item, dict):
                state = str(item.get("state") or "pending")
                rows.append((item, _("External · {state}").format(state=state)))
        for item in self.status.get("members") or []:
            if isinstance(item, dict):
                rows.append((item, _("Member")))
        return rows

    def _render_people(self) -> None:
        child = self.people.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.people.remove(child)
            child = nxt
        rows = self._people_rows()
        self.people_empty.set_visible(not rows)
        self.people.set_visible(bool(rows))
        for person, kind in rows:
            email = member_email(person)
            role = member_role(person)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_start=12, margin_end=8, margin_top=8, margin_bottom=8)
            label = Gtk.Label(label=_("{email} · {role} · {kind}").format(email=email or _("Unknown"), role=role, kind=kind), xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
            row.append(label)
            if email and self.window.section != "/shared-with-me":
                remove = Gtk.Button(label=_("Remove"), valign=Gtk.Align.CENTER)
                remove.connect("clicked", self._remove_email, email)
                row.append(remove)
            self.people.append(row)

    def _render_link(self) -> None:
        access = self.status.get("urlAccess")
        url = ""
        if isinstance(access, dict):
            url = str(access.get("url") or "")
        if url:
            role = str(access.get("role") or "viewer")
            self.link_label.set_text(_("{url}\nRole: {role}").format(url=url, role=role))
            self.link_copy.set_sensitive(True)
            self.link_remove.set_sensitive(True)
        else:
            self.link_label.set_text(_("No public link"))
            self.link_copy.set_sensitive(False)
            self.link_remove.set_sensitive(False)

    def _invite_role(self) -> str:
        index = int(self.role.get_selected())
        if 0 <= index < len(_INVITE_ROLES):
            return _INVITE_ROLES[index]
        return "viewer"

    def _url_role(self) -> str:
        index = int(self.link_role.get_selected())
        if 0 <= index < len(_LINK_ROLES):
            return _LINK_ROLES[index]
        return "viewer"

    def _invite(self, *_args) -> None:
        emails = [part.strip() for part in self.email.get_text().replace(";", ",").split(",") if part.strip()]
        if not emails:
            self.window._toast(_("Enter an email to invite"))
            return
        if any("@" not in email for email in emails):
            self.window._toast(_("Enter a valid email address"))
            return
        path = self.item.path
        role = self._invite_role()
        message = self.message.get_text().strip() or None
        include = bool(self.include_name.get_active())

        def work():
            return self.window.cli.sharing_invite(path, emails, role=role, message=message, include_node_name=include)

        def done(result) -> None:
            self.email.set_text("")
            self.window._toast(_("Invitation sent"))
            self._on_status(result)

        self.window._bg(work, done, self.window._share_error)

    def _remove_email(self, _button, email: str) -> None:
        path = self.item.path

        def work():
            self.window.cli.sharing_remove(path, emails=[email])
            return self.window.cli.sharing_status(path)

        def done(status) -> None:
            self.window._toast(_("Removed {email}").format(email=email))
            self._on_status(status)

        self.window._bg(work, done, self.window._share_error)

    def _set_url(self, *_args) -> None:
        path = self.item.path
        role = self._url_role()
        password = self.link_password.get_text().strip() or None
        expiration = self.link_expiration.get_text().strip() or None

        def work():
            return self.window.cli.sharing_set_url(path, role=role, password=password, expiration=expiration)

        def done(result) -> None:
            self.window._toast(_("Public link updated"))
            self._on_status(result)

        self.window._bg(work, done, self.window._share_error)

    def _copy_url(self, *_args) -> None:
        access = self.status.get("urlAccess")
        url = str(access.get("url") or "") if isinstance(access, dict) else ""
        if not url:
            self.window._toast(_("No public link"))
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(url)
        self.window._toast(_("Link copied"))

    def _remove_url(self, *_args) -> None:
        path = self.item.path

        def work():
            self.window.cli.sharing_remove_url(path)
            return self.window.cli.sharing_status(path)

        def done(status) -> None:
            self.window._toast(_("Public link removed"))
            self._on_status(status)

        self.window._bg(work, done, self.window._share_error)

    def _leave(self, *_args) -> None:
        path = self.item.path

        def work():
            self.window.cli.sharing_leave(path)
            return True

        def done(_ok) -> None:
            self.window._toast(_("Left share"))
            self.close()
            self.window.reload()

        self.window._bg(work, done, self.window._share_error)

    def _stop(self, *_args) -> None:
        path = self.item.path

        def work():
            self.window.cli.sharing_remove(path, everyone=True)
            try:
                self.window.cli.sharing_remove_url(path)
            except CliError:
                pass
            return True

        def done(_ok) -> None:
            self.window._toast(_("Stopped sharing"))
            self.close()
            self.window.reload()

        self.window._bg(work, done, self.window._share_error)


class DriveApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._window: DriveWindow | None = None
        self._tray: StatusNotifierTray | None = None
        self._allow_quit = False
        self._sync_proc: subprocess.Popen | None = None
        self._path_monitor: GioTreeMonitor | MultiGioTreeMonitor | None = None
        self._path_debounce_source = 0
        self.app_menu = self._build_app_menu()
        self._install_actions()
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _build_app_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        settings = Gio.Menu()
        settings.append(_("Settings"), "app.preferences")
        settings.append(_("Guided setup"), "app.guided-setup")
        settings.append(_("Open Drive in browser"), "app.open-browser")
        settings.append(_("Open always-on folder"), "app.open-sync")
        menu.append_section(None, settings)
        help_section = Gio.Menu()
        help_section.append(_("Proton Drive Help"), "app.help")
        help_section.append(_("Drive CLI Help"), "app.cli-help")
        help_section.append(_("Guided setup"), "app.guided-setup")
        help_section.append(_("Open CLI logs"), "app.logs")
        menu.append_section(None, help_section)
        about = Gio.Menu()
        about.append(_("About Proton Drive Desktop"), "app.about")
        menu.append_section(None, about)
        quit_section = Gio.Menu()
        quit_section.append(_("Quit"), "app.quit")
        menu.append_section(None, quit_section)
        return menu

    def _install_actions(self) -> None:
        actions = {
            "preferences": self._on_preferences,
            "guided-setup": self._on_guided_setup,
            "open-browser": lambda *_: self._open_url(DRIVE_WEB_URL),
            "open-sync": self._on_open_sync,
            "help": lambda *_: self._open_url(HELP_URL),
            "cli-help": lambda *_: self._open_url(CLI_HELP_URL),
            "logs": self._on_open_logs,
            "about": self._on_about,
            "quit": lambda *_: self.quit_from_tray(),
        }
        for name, handler in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        self.set_accels_for_action("app.preferences", ["<primary>comma"])
        self.set_accels_for_action("app.help", ["F1"])
        self.set_accels_for_action("app.quit", ["<primary>q"])

    def _on_activate(self, _app) -> None:
        _register_icon_theme()
        Gtk.Window.set_default_icon_name(APP_ICON_NAME)
        provider = Gtk.CssProvider()
        css = _css_path()
        if Path(css).is_file():
            provider.load_from_path(css)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        if self._window is None:
            self._window = DriveWindow(self)
            self._window.connect("close-request", self._on_window_close)
            cfg = load_config()
            self._tray = StatusNotifierTray(
                app_id=APP_ID,
                title=_("Proton Drive"),
                icon_name=APP_ICON_NAME,
                icon_theme_path=str(hicolor_dir()),
                icon_png=icon_png(32),
                on_show=self.show_window,
                on_hide=self.hide_window,
                on_open_files=self.open_my_files,
                on_open_sync=self._on_open_sync,
                on_open_browser=lambda: self._open_url(DRIVE_WEB_URL),
                on_settings=self._on_preferences,
                on_help=lambda: self._open_url(HELP_URL),
                on_quit=self.quit_from_tray,
                on_toggle_sync_pause=self._on_tray_toggle_pause,
            )
            self._tray.start()
            self._tray.set_sync_paused(
                bool(cfg.get("sync_paused")),
                enabled=bool(cfg.get("sync_enabled")),
            )
            GLib.timeout_add_seconds(20, self._on_sync_tick)
            if cfg.get("sync_enabled") and not cfg.get("sync_paused"):
                self._sync_proc = spawn_worker(force=False)
            self.refresh_path_trigger_watch()
            if not cfg.get("setup_completed"):
                GLib.idle_add(self._present_guided_setup)
        self._window.present()

    def _on_tray_toggle_pause(self) -> None:
        cfg = load_config()
        self.set_sync_paused(not bool(cfg.get("sync_paused")))

    def _on_guided_setup(self, *_args) -> None:
        self._present_guided_setup()

    def _present_guided_setup(self) -> bool:
        if self._window is None:
            return False
        GuidedSetupDialog(self._window).present(self._window)
        return False

    def set_sync_paused(self, paused: bool) -> None:
        cfg = load_config()
        cfg["sync_paused"] = bool(paused)
        save_config(cfg)
        if paused:
            self._stop_sync_worker()
            mark_worker_paused()
        else:
            mark_worker_idle()
            if cfg.get("sync_enabled"):
                self.start_sync_now()
        self._refresh_sync_label()
        if self._tray is not None:
            self._tray.set_sync_paused(
                bool(paused),
                enabled=bool(cfg.get("sync_enabled")),
            )
        self.refresh_path_trigger_watch()

    def _on_window_close(self, *_args) -> bool:
        if self._window is not None:
            self._window._persist_window_state()
            self._window._persist_last_path()
        if self._allow_quit or self._tray is None or not self._tray.started:
            return False
        self.hide_window()
        return True

    def show_window(self) -> None:
        if self._window is not None:
            self._window.set_visible(True)
            self._window.present()

    def hide_window(self) -> None:
        if self._window is not None:
            self._window.set_visible(False)

    def open_my_files(self) -> None:
        self.show_window()
        if self._window is not None:
            self._window.open_section("/my-files")

    def relaunch(self) -> None:
        """Replace this Gio process so gettext and GTK pick up the saved language."""
        self._allow_quit = True
        self._stop_sync_worker()
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        restore_session_locale_env()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def quit_from_tray(self) -> None:
        self._allow_quit = True
        self._stop_path_trigger_watch()
        self._stop_sync_worker()
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self.quit()

    def _on_shutdown(self, *_args) -> None:
        if self._window is not None:
            self._window._persist_window_state()
            self._window._persist_last_path()
        self._stop_path_trigger_watch()
        self._stop_sync_worker()
        set_gui_busy(False)

    def _refresh_sync_label(self) -> None:
        if self._window is not None:
            self._window.sync_label.set_text(format_status_line())

    def _on_sync_tick(self) -> bool:
        self._refresh_sync_label()
        cfg = load_config()
        if not cfg.get("sync_enabled"):
            return True
        if sync_is_paused(cfg):
            return True
        if self._sync_proc is not None and self._sync_proc.poll() is None:
            return True
        idle = self._window is None or not self._window.busy
        if not idle:
            return True
        if not due_for_pass(cfg=cfg):
            return True
        self._sync_proc = spawn_worker(force=False)
        return True

    def start_sync_now(self) -> None:
        cfg = load_config()
        if cfg.get("sync_paused"):
            self.set_sync_paused(False)
            return
        if self._sync_proc is not None and self._sync_proc.poll() is None:
            self._refresh_sync_label()
            return
        self._sync_proc = spawn_worker(force=True)
        self._refresh_sync_label()

    def _stop_sync_worker(self) -> None:
        running = self._sync_proc is not None and self._sync_proc.poll() is None
        if running:
            self._sync_proc.terminate()
            mark_worker_idle()
        self._sync_proc = None

    def _cancel_path_debounce(self) -> None:
        if self._path_debounce_source:
            GLib.source_remove(self._path_debounce_source)
            self._path_debounce_source = 0

    def _stop_path_trigger_watch(self) -> None:
        self._cancel_path_debounce()
        if self._path_monitor is not None:
            self._path_monitor.stop()
            self._path_monitor = None

    def refresh_path_trigger_watch(self) -> None:
        """Start or stop the Gio/inotify tree watch from current Settings."""
        cfg = load_config()
        want = bool(cfg.get("sync_enabled") and cfg.get("sync_path_trigger") and not cfg.get("sync_paused"))
        folders = sync_pair_local_paths(cfg, enabled_only=True)
        if not want or not local_watch_available() or not folders:
            self._stop_path_trigger_watch()
            return
        resolved: list[Path] = []
        for folder in folders:
            path = Path(folder).expanduser()
            try:
                resolved.append(path.resolve())
            except OSError:
                resolved.append(path)
        if self._path_monitor is not None:
            current = getattr(self._path_monitor, "roots", None)
            if current is None and hasattr(self._path_monitor, "root"):
                current = [self._path_monitor.root]
            if current is not None and list(current) == resolved:
                return
            self._stop_path_trigger_watch()
        if len(resolved) == 1:
            monitor: GioTreeMonitor | MultiGioTreeMonitor = GioTreeMonitor(
                resolved[0], self._on_path_trigger_fs_change
            )
        else:
            monitor = MultiGioTreeMonitor(resolved, self._on_path_trigger_fs_change)
        if not monitor.start():
            self._path_monitor = None
            return
        self._path_monitor = monitor

    def _on_path_trigger_fs_change(self) -> None:
        self._cancel_path_debounce()
        self._path_debounce_source = GLib.timeout_add_seconds(
            PATH_TRIGGER_DEBOUNCE_SECONDS,
            self._on_path_trigger_debounce_fire,
        )

    def _on_path_trigger_debounce_fire(self) -> bool:
        self._path_debounce_source = 0
        cfg = load_config()
        if (
            not cfg.get("sync_enabled")
            or not cfg.get("sync_path_trigger")
            or cfg.get("sync_paused")
        ):
            return False
        request_pass_soon()
        if self._sync_proc is not None and self._sync_proc.poll() is None:
            self._refresh_sync_label()
            return False
        idle = self._window is None or not self._window.busy
        if idle:
            self._sync_proc = spawn_worker(force=False)
        self._refresh_sync_label()
        return False

    def _on_open_sync(self, *_args) -> None:
        folders = sync_pair_local_paths(enabled_only=False)
        folder = Path(folders[0]).expanduser() if folders else configured_sync_folder()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _open_url(self, url: str, *_args) -> None:
        parent = self._window
        try:
            Gtk.UriLauncher.new(url).launch(parent, None, None)
        except Exception:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _on_open_logs(self, *_args) -> None:
        folder = cli_data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name="Proton Drive Desktop",
            application_icon=APP_ICON_NAME,
            developer_name="VoxHash Technologies",
            version=__version__,
            comments=_("Unofficial GTK4 GUI for Proton’s official Drive CLI. Not affiliated with Proton AG."),
            website=WEBSITE_URL,
            issue_url=ISSUE_URL,
            copyright=_("GUI © 2026 VoxHash Technologies. Proton Drive mark © Proton AG."),
            license_type=Gtk.License.MIT_X11,
        )
        about.add_link(_("Proton Drive Help"), HELP_URL)
        about.add_link(_("Terms of Service"), TERMS_URL)
        about.add_link(_("Privacy Policy"), PRIVACY_URL)
        if self._window is not None:
            try:
                info = self._window.cli.version_info()
                about.set_debug_info(info.raw)
                about.set_comments(
                    _("Unofficial GTK4 GUI for Proton’s official Drive CLI. Not affiliated with Proton AG. Official CLI {version}: {status}").format(
                        version=info.cli_version or info.app_version,
                        status=info.status_line,
                    )
                )
                if info.update_available:
                    about.add_link(_("Download Proton Drive CLI"), info.download_url or CLI_DOWNLOAD_URL)
                    about.add_link(_("Drive CLI Help"), CLI_HELP_URL)
            except Exception as exc:  # noqa: BLE001
                about.set_debug_info(str(exc))
            about.present(self._window)
        else:
            about.present()

    def _on_preferences(self, *_args) -> None:
        self.show_window()
        if self._window is None:
            return
        SettingsDialog(self._window).present(self._window)


def _register_icon_theme() -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    theme = Gtk.IconTheme.get_for_display(display)
    search = str(icon_theme_search_path())
    if search not in theme.get_search_path():
        theme.add_search_path(search)


def _set_autostart(enabled: bool) -> None:
    path = xdg_autostart_path()
    if not enabled:
        if path.is_file():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    command = shutil.which("proton-drive-desktop") or str(repo_root() / "scripts" / "proton-drive-desktop")
    path.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Proton Drive",
                f"Exec={command}",
                f"Icon={APP_ICON_NAME}",
                "X-GNOME-Autostart-enabled=true",
                "StartupNotify=false",
                "",
            ]
        ),
        encoding="utf-8",
    )


class GuidedSetupDialog(Adw.MessageDialog):
    """Short first-run / Help flow: CLI verify, preview, seed, enable always-on."""

    def __init__(self, window: DriveWindow) -> None:
        super().__init__(
            transient_for=window,
            heading=_("Welcome to Proton Drive Desktop"),
            body=_(
                "This GTK app uses the official proton-drive CLI (not FUSE). "
                "This short setup verifies the CLI checksum, previews always-on sync, "
                "optionally assumes both sides already match, then enables the worker.\n\n"
                "Choose a step below. You can reopen this from Help or Settings anytime."
            ),
        )
        self.window = window
        self.add_response("skip", _("Skip"))
        self.add_response("verify", _("Verify CLI"))
        self.add_response("preview", _("Preview sync"))
        self.add_response("seed", _("Assume synced"))
        self.add_response("enable", _("Enable always-on"))
        self.set_default_response("verify")
        self.set_response_appearance("enable", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self._on_response)

    def _mark_completed(self) -> None:
        cfg = load_config()
        cfg["setup_completed"] = True
        save_config(cfg)

    def _on_response(self, _dialog, response: str) -> None:
        if response in {"skip", "verify", "preview", "seed", "enable"}:
            self._mark_completed()
        if response == "skip":
            return
        if response == "verify":
            self.window._bg(
                lambda: verify_proton_drive_binary(force=True),
                self._on_verify_done,
                lambda exc: self.window._toast(str(exc)[:160]),
            )
            return
        if response == "preview":
            cfg = load_config()
            Path(str(cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(
                parents=True, exist_ok=True
            )

            def work():
                return preview_pass(cfg=cfg, cli=self.window.cli)

            def done(preview: dict) -> None:
                dialog = Adw.MessageDialog(
                    transient_for=self.window,
                    heading=_("Always-on folder preview"),
                    body=format_preview_message(preview, offer_seed=True),
                )
                dialog.add_response("ok", _("OK"))
                dialog.add_response("seed", _("Assume already synced"))
                dialog.set_default_response("ok")
                dialog.connect(
                    "response",
                    lambda _d, resp: self._seed_from_guided() if resp == "seed" else None,
                )
                dialog.present()

            def failed(exc: BaseException) -> None:
                if isinstance(exc, NotLoggedIn):
                    self.window._toast(_("Sign in required for always-on preview"))
                else:
                    self.window._toast(
                        _("Always-on preview failed: {error}").format(error=str(exc)[:120])
                    )

            self.window._bg(work, done, failed)
            return
        if response == "seed":
            self._seed_from_guided()
            return
        if response == "enable":
            settings = SettingsDialog(self.window)
            settings.present(self.window)
            settings.sync_switch.set_active(True)

    def _seed_from_guided(self) -> None:
        cfg = load_config()
        Path(str(cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(
            parents=True, exist_ok=True
        )

        def work():
            return seed_sync_delta(cfg=cfg, cli=self.window.cli)

        def done(result: dict) -> None:
            self.window._toast(format_seed_message(result))

        def failed(exc: BaseException) -> None:
            if isinstance(exc, NotLoggedIn):
                self.window._toast(_("Sign in required to assume already synced"))
            else:
                self.window._toast(
                    _("Assume already synced failed: {error}").format(error=str(exc)[:120])
                )

        self.window._bg(work, done, failed)

    def _on_verify_done(self, result) -> None:
        if getattr(result, "should_warn", False):
            self.window._toast(_("CLI checksum warning — see Settings for details"))
        elif getattr(result, "matched", None) is False:
            self.window._toast(_("CLI checksum did not match Proton’s published SHA-512"))
        else:
            self.window._toast(_("CLI checksum checked"))
        GuidedSetupDialog(self.window).present(self.window)


class SettingsDialog(Adw.PreferencesDialog):
    """Settings mapped to live CLI session + local GUI config that actually exists."""

    def __init__(self, window: DriveWindow) -> None:
        super().__init__(title=_("Settings"))
        self.window = window
        self.cfg = load_config()
        self.set_content_width(560)

        account = Adw.PreferencesPage(title=_("Account"), icon_name="avatar-default-symbolic")
        app_page = Adw.PreferencesPage(title=_("Application"), icon_name="applications-system-symbolic")
        self.add(account)
        self.add(app_page)

        who = Adw.PreferencesGroup(
            title=_("Proton account"),
            description=_("Taken from the official CLI session in the system keyring."),
        )
        self.email_row = Adw.ActionRow(title=_("Signed in as"), subtitle=window.email or _("Reading live session…"))
        account_btn = Gtk.Button(label=_("Proton Account"), valign=Gtk.Align.CENTER)
        account_btn.connect("clicked", lambda *_: window.get_application()._open_url(ACCOUNT_URL))
        self.email_row.add_suffix(account_btn)
        who.add(self.email_row)
        self.quota_row = Adw.ActionRow(
            title=_("Storage quota"),
            subtitle=_("Probing official CLI…"),
        )
        who.add(self.quota_row)
        self.cli_version_row = Adw.ActionRow(title=_("CLI version"), subtitle=_("Reading proton-drive version…"))
        who.add(self.cli_version_row)
        self.cli_update_row = Adw.ActionRow(title=_("CLI updates"), subtitle=_("Checking proton-drive version…"))
        self._cli_download_url = CLI_DOWNLOAD_URL
        self.cli_download_btn = Gtk.Button(label=_("Download"), valign=Gtk.Align.CENTER)
        self.cli_download_btn.connect("clicked", lambda *_: window.get_application()._open_url(self._cli_download_url))
        self.cli_help_btn = Gtk.Button(label=_("CLI Help"), valign=Gtk.Align.CENTER)
        self.cli_help_btn.connect("clicked", lambda *_: window.get_application()._open_url(CLI_HELP_URL))
        self.cli_download_btn.set_visible(False)
        self.cli_help_btn.set_visible(False)
        self.cli_update_row.add_suffix(self.cli_help_btn)
        self.cli_update_row.add_suffix(self.cli_download_btn)
        who.add(self.cli_update_row)
        signout = Adw.ButtonRow(title=_("Sign out"))
        signout.add_css_class("destructive-action")
        signout.connect("activated", self._sign_out)
        who.add(signout)
        account.add(who)

        cli_group = Adw.PreferencesGroup(
            title=_("Official CLI"),
            description=_("This GUI only runs the proton-drive binary already installed on this machine. proton-drive version reports the installed CLI and whether Proton has a newer one. This app does not download Proton binaries."),
        )
        self.cli_row = Adw.ActionRow(title=_("CLI path"), subtitle=self._cli_path_text())
        choose_cli = Gtk.Button(label=_("Choose"), valign=Gtk.Align.CENTER)
        choose_cli.connect("clicked", self._choose_cli)
        self.cli_row.add_suffix(choose_cli)
        cli_group.add(self.cli_row)
        account.add(cli_group)

        appearance = Adw.PreferencesGroup(title=_("Appearance"))
        themes = Gtk.StringList.new([_("Dark"), _("Light"), _("System")])
        self.theme_row = Adw.ComboRow(title=_("Theme"), model=themes)
        current = str(self.cfg.get("theme") or "dark").lower()
        self.theme_row.set_selected({"dark": 0, "light": 1, "system": 2}.get(current, 0))
        self.theme_row.connect("notify::selected", self._on_theme)
        appearance.add(self.theme_row)
        choices = language_choices()
        languages = Gtk.StringList.new([label for _code, label in choices])
        self.language_row = Adw.ComboRow(
            title=_("Language"),
            subtitle=_("Same as Proton Drive on Windows: System default follows the OS locale. English, Russian, Simplified Chinese, Arabic, Italian, Portuguese, Spanish, Korean, and Japanese load this app’s catalogs. Changing language restarts the app. Arabic uses a right-to-left layout."),
            model=languages,
        )
        current_lang = normalize_language(self.cfg.get("language"))
        codes = [code for code, _label in choices]
        self.language_row.set_selected(codes.index(current_lang) if current_lang in codes else 0)
        self.language_row.connect("notify::selected", self._on_language)
        appearance.add(self.language_row)
        app_page.add(appearance)

        folders = Adw.PreferencesGroup(
            title=_("Downloads"),
            description=_("One-off downloads from the toolbar. This is not the always-on folder."),
        )
        self.download_row = Adw.ActionRow(title=_("Download folder"), subtitle=str(download_folder()))
        choose_dl = Gtk.Button(label=_("Choose"), valign=Gtk.Align.CENTER)
        choose_dl.connect("clicked", self._choose_download)
        self.download_row.add_suffix(choose_dl)
        folders.add(self.download_row)
        app_page.add(folders)

        sync = Adw.PreferencesGroup(
            title=_("Always-on folder"),
            description=_(
                "Official CLI 0.8.0 cannot FUSE-mount Drive and has no Activity log. "
                "Enable keeps one or more local directories in sync with chosen /my-files "
                "paths (or subtrees) via a niced filesystem download/upload worker, starts "
                "that worker now, and turns on session autostart so it stays on after login. "
                "Add extra pairs below when you need more than one folder. Default direction "
                "is bidirectional; upload-only or download-only run one half of the pass. "
                "Default conflict policy is skip files / merge folders; rename keeps both "
                "file copies with a unique suffix. Existing files are never replaced or "
                "removed. Worker, last pass, history, and errors below come from this app's "
                "worker lock and ~/.config/proton-drive-desktop/sync-status.json."
            ),
        )
        self.sync_switch = Adw.SwitchRow(
            title=_("Enable always-on folder"),
            subtitle=_("Shows a dry-run preview, then starts the CLI worker now and with this session. Not a kernel mount."),
        )
        self._sync_switch_guard = False
        self._sync_preview_busy = False
        self.sync_switch.set_active(bool(self.cfg.get("sync_enabled")))
        self.sync_switch.connect("notify::active", self._on_sync_enabled)
        sync.add(self.sync_switch)
        self._sync_pause_guard = False
        self.sync_pause_row = Adw.SwitchRow(
            title=_("Pause sync"),
            subtitle=_("Keep always-on enabled but skip worker passes until you resume (Settings or tray)."),
        )
        self.sync_pause_row.set_active(bool(self.cfg.get("sync_paused")))
        self.sync_pause_row.set_sensitive(bool(self.cfg.get("sync_enabled")))
        self.sync_pause_row.connect("notify::active", self._on_sync_paused)
        sync.add(self.sync_pause_row)
        self.sync_seed_row = Adw.ActionRow(
            title=_("Assume already synced"),
            subtitle=_(
                "Record current local and remote fingerprints into delta state so the "
                "next pass skips bulk transfer when both sides already match. Uses a "
                "real Drive list — does not upload or download."
            ),
        )
        seed_btn = Gtk.Button(label=_("Seed"), valign=Gtk.Align.CENTER)
        seed_btn.connect("clicked", self._on_sync_seed)
        self.sync_seed_row.add_suffix(seed_btn)
        sync.add(self.sync_seed_row)
        guided_row = Adw.ActionRow(
            title=_("Guided setup"),
            subtitle=_("Short Adw flow: CLI checksum, preview, seed/assume-synced, enable always-on."),
        )
        guided_btn = Gtk.Button(label=_("Open"), valign=Gtk.Align.CENTER)
        guided_btn.connect("clicked", lambda *_: window.get_application()._on_guided_setup())
        guided_row.add_suffix(guided_btn)
        sync.add(guided_row)
        self.sync_folder_row = Adw.ActionRow(title=_("Folder"), subtitle=str(self.cfg.get("sync_folder") or configured_sync_folder()))
        choose_sync = Gtk.Button(label=_("Choose"), valign=Gtk.Align.CENTER)
        choose_sync.connect("clicked", self._choose_sync)
        self.sync_folder_row.add_suffix(choose_sync)
        open_sync = Gtk.Button(label=_("Open"), valign=Gtk.Align.CENTER)
        open_sync.connect("clicked", lambda *_: window.get_application()._on_open_sync())
        self.sync_folder_row.add_suffix(open_sync)
        sync.add(self.sync_folder_row)
        self.sync_exclude_row = Adw.EntryRow(title=_("Exclude patterns"))
        self.sync_exclude_row.set_text(str(self.cfg.get("sync_exclude") or ""))
        self.sync_exclude_row.set_show_apply_button(True)
        self.sync_exclude_row.set_tooltip_text(
            _(
                "gitignore-style globs for top-level always-on names. "
                "Separate with commas or newlines. # comments and !negation are supported. "
                "Example: *.tmp, node_modules, !keep.tmp"
            )
        )
        self.sync_exclude_row.connect("apply", self._on_sync_exclude_apply)
        sync.add(self.sync_exclude_row)
        self.sync_remote_row = Adw.EntryRow(title=_("Remote root"))
        self.sync_remote_row.set_text(str(self.cfg.get("sync_remote_root") or "/my-files"))
        self.sync_remote_row.set_show_apply_button(True)
        self.sync_remote_row.set_tooltip_text(
            _(
                "Drive path to sync with the local always-on folder. "
                "Must be /my-files or a folder under it, for example /my-files/Work."
            )
        )
        self.sync_remote_row.connect("apply", self._on_sync_remote_apply)
        sync.add(self.sync_remote_row)
        conflict_labels = Gtk.StringList.new(
            [
                _("Skip existing files (merge folders)"),
                _("Rename conflicting files (merge folders)"),
            ]
        )
        self.sync_conflict_row = Adw.ComboRow(
            title=_("Conflict policy"),
            subtitle=_(
                "Official CLI filesystem -f / -d. Skip leaves existing files unchanged "
                "(default). Rename adds a unique suffix so both copies are kept. Folders "
                "always merge. replace/remove are not offered."
            ),
            model=conflict_labels,
        )
        current_conflict = normalize_sync_conflict_policy(self.cfg.get("sync_conflict_policy"))
        self.sync_conflict_row.set_selected(1 if current_conflict == "rename" else 0)
        self.sync_conflict_row.connect("notify::selected", self._on_sync_conflict_policy)
        sync.add(self.sync_conflict_row)
        direction_labels = Gtk.StringList.new(
            [
                _("Bidirectional (download then upload)"),
                _("Upload only (local → Drive)"),
                _("Download only (Drive → local)"),
            ]
        )
        self.sync_direction_row = Adw.ComboRow(
            title=_("Sync direction"),
            subtitle=_(
                "Bidirectional is the desktop default. Upload only is one-way local → Drive "
                "(what TrueNAS-style backup scripts need). Download only pulls remote "
                "children and never uploads."
            ),
            model=direction_labels,
        )
        current_direction = normalize_sync_direction(self.cfg.get("sync_direction"))
        direction_index = {"bidirectional": 0, "upload-only": 1, "download-only": 2}.get(
            current_direction, 0
        )
        self.sync_direction_row.set_selected(direction_index)
        self.sync_direction_row.connect("notify::selected", self._on_sync_direction)
        sync.add(self.sync_direction_row)
        self._sync_interval_guard = False
        current_interval = normalize_sync_interval_seconds(self.cfg.get("sync_interval_seconds"))
        self.sync_interval_row = Adw.SpinRow.new_with_range(
            float(SYNC_INTERVAL_SECONDS_MIN),
            float(SYNC_INTERVAL_SECONDS_MAX),
            30.0,
        )
        self.sync_interval_row.set_title(_("Sync interval (seconds)"))
        self.sync_interval_row.set_subtitle(
            _(
                "How often the always-on worker runs a pass when idle. "
                "Also updates the optional systemd user timer. Range {min}–{max}; default 300."
            ).format(min=SYNC_INTERVAL_SECONDS_MIN, max=SYNC_INTERVAL_SECONDS_MAX)
        )
        self.sync_interval_row.set_digits(0)
        self.sync_interval_row.set_value(float(current_interval))
        self.sync_interval_row.connect("notify::value", self._on_sync_interval)
        sync.add(self.sync_interval_row)
        self._sync_pass_timeout_guard = False
        current_pass_timeout = normalize_sync_pass_timeout_seconds(
            self.cfg.get("sync_pass_timeout_seconds")
        )
        self.sync_pass_timeout_switch = Adw.SwitchRow(
            title=_("Per-pass timeout"),
            subtitle=_(
                "Optional watchdog for each always-on pass (TrueNAS-style). "
                "When the budget is exceeded, the worker cancels the owned CLI "
                "transfer process tree so a hung upload/download cannot block forever. "
                "Off by default."
            ),
        )
        self.sync_pass_timeout_switch.set_active(current_pass_timeout > 0)
        self.sync_pass_timeout_switch.connect("notify::active", self._on_sync_pass_timeout_enabled)
        sync.add(self.sync_pass_timeout_switch)
        self.sync_pass_timeout_row = Adw.SpinRow.new_with_range(
            float(SYNC_PASS_TIMEOUT_SECONDS_MIN),
            float(SYNC_PASS_TIMEOUT_SECONDS_MAX),
            60.0,
        )
        self.sync_pass_timeout_row.set_title(_("Pass timeout (seconds)"))
        self.sync_pass_timeout_row.set_subtitle(
            _(
                "Maximum duration of one sync pass before the watchdog fires. "
                "Range {min}–{max}; suggested {suggested} when enabling."
            ).format(
                min=SYNC_PASS_TIMEOUT_SECONDS_MIN,
                max=SYNC_PASS_TIMEOUT_SECONDS_MAX,
                suggested=SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED,
            )
        )
        self.sync_pass_timeout_row.set_digits(0)
        self.sync_pass_timeout_row.set_value(
            float(current_pass_timeout or SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED)
        )
        self.sync_pass_timeout_row.set_sensitive(current_pass_timeout > 0)
        self.sync_pass_timeout_row.connect("notify::value", self._on_sync_pass_timeout)
        sync.add(self.sync_pass_timeout_row)
        self._path_trigger_guard = False
        watch_ok = local_watch_available()
        systemd_ok_for_path = systemd_user_available()
        self.path_trigger_row = Adw.SwitchRow(
            title=_("Sync soon after local edits"),
            subtitle="",
        )
        self._apply_path_trigger_subtitle(
            watch_ok=watch_ok,
            systemd_ok=systemd_ok_for_path,
        )
        if not watch_ok and not systemd_ok_for_path:
            self.path_trigger_row.set_sensitive(False)
        self.path_trigger_row.set_active(
            bool(self.cfg.get("sync_path_trigger")) and (watch_ok or systemd_ok_for_path)
        )
        self.path_trigger_row.connect("notify::active", self._on_path_trigger)
        sync.add(self.path_trigger_row)
        self.sync_worker_row = Adw.ActionRow(title=_("Worker"), subtitle=_("Stopped"))
        sync_now = Gtk.Button(label=_("Sync now"), valign=Gtk.Align.CENTER)
        sync_now.connect("clicked", self._sync_now)
        self.sync_worker_row.add_suffix(sync_now)
        sync.add(self.sync_worker_row)
        self.sync_last_pass_row = Adw.ActionRow(title=_("Last successful pass"), subtitle=_("Never"))
        sync.add(self.sync_last_pass_row)
        self.sync_files_row = Adw.ActionRow(title=_("Files last pass"), subtitle=_("No completed pass yet"))
        sync.add(self.sync_files_row)
        self.sync_error_row = Adw.ActionRow(title=_("Last error"), subtitle=_("None"))
        sync.add(self.sync_error_row)
        self.sync_history_row = Adw.ActionRow(
            title=_("Recent passes"),
            subtitle=_("No history yet"),
        )
        self.sync_history_row.set_subtitle_lines(6)
        sync.add(self.sync_history_row)
        app_page.add(sync)

        pairs_group = Adw.PreferencesGroup(
            title=_("Sync pairs"),
            description=_(
                "Each pair maps one local folder to a /my-files path. The first pair is "
                "edited by Folder / Remote root / Exclude / Conflict / Direction above. "
                "Extra pairs are listed here; the worker runs enabled pairs in order under "
                "one lock."
            ),
        )
        self._sync_pairs_group = pairs_group
        self._sync_pair_rows: list[Adw.ActionRow] = []
        add_pair_row = Adw.ActionRow(title=_("Add sync pair"))
        add_pair_btn = Gtk.Button(label=_("Add"), valign=Gtk.Align.CENTER)
        add_pair_btn.connect("clicked", self._on_add_sync_pair)
        add_pair_row.add_suffix(add_pair_btn)
        pairs_group.add(add_pair_row)
        app_page.add(pairs_group)
        self._rebuild_sync_pair_rows()

        self._activity_alive = True
        self._activity_source = GLib.timeout_add_seconds(2, self._on_activity_tick)
        self.connect("closed", self._on_settings_closed)
        self._apply_activity()

        startup = Adw.PreferencesGroup(
            title=_("Startup"),
            description=_(
                "XDG autostart launches this GUI with the session so the always-on worker "
                "comes back after login. An optional systemd user timer runs one sync pass "
                "on a fixed interval without needing the window open. Both can be on together."
            ),
        )
        self.autostart_row = Adw.SwitchRow(title=_("Start with this session"))
        self.autostart_row.set_active(xdg_autostart_path().is_file())
        self.autostart_row.connect("notify::active", self._on_autostart)
        startup.add(self.autostart_row)
        self._systemd_switch_guard = False
        systemd_ok = systemd_user_available()
        self.systemd_row = Adw.SwitchRow(
            title=_("systemd user timer"),
            subtitle="",
        )
        self._apply_systemd_interval_subtitle(available=systemd_ok)
        if not systemd_ok:
            self.systemd_row.set_sensitive(False)
        self.systemd_row.set_active(bool(systemd_ok and sync_timer_is_enabled()))
        self.systemd_row.connect("notify::active", self._on_systemd_sync)
        startup.add(self.systemd_row)
        app_page.add(startup)

        window._bg(self._load_live, self._on_live, self._on_live_error)
        window._bg(self._verify_cli_checksum, self._on_cli_checksum, lambda *_: None)

    def _verify_cli_checksum(self):
        return verify_proton_drive_binary()

    def _on_cli_checksum(self, result) -> None:
        if not getattr(result, "should_warn", False):
            return
        body = _(
            "The proton-drive binary at {path} does not match any SHA-512 published by Proton "
            "for Linux (digest {digest}…). This app will not replace it. Download a fresh CLI "
            "from proton.me if you did not build it yourself."
        ).format(
            path=result.path,
            digest=(result.digest[:16] if result.digest else "?"),
        )
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=_("CLI checksum warning"),
            body=body,
        )
        dialog.add_response("ok", _("OK"))
        dialog.add_response("download", _("Download"))
        dialog.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_checksum_dialog)
        dialog.present()

    def _on_checksum_dialog(self, dialog, response: str) -> None:
        if response == "download":
            self.window.get_application()._open_url(CLI_DOWNLOAD_URL)

    def _cli_path_text(self) -> str:
        try:
            return find_binary()
        except CliError as exc:
            return str(exc)

    def _load_live(self) -> dict:
        cli = self.window.cli
        email = self.window.email
        try:
            nodes = cli.list("/my-files")
            found = account_email(nodes)
            if found:
                email = found
        except NotLoggedIn:
            email = ""
        help_text = cli.help_text()
        return {
            "email": email,
            "version": cli.version_info(),
            "path": find_binary(),
            "quota_available": cli_help_exposes_storage_quota(help_text),
        }

    def _apply_quota_probe(self, available: bool) -> None:
        """Show real CLI probe result only — never invent used/total storage numbers."""
        if available:
            self.quota_row.set_subtitle(
                _(
                    "Official CLI help lists a quota-related command; "
                    "this app does not display values until a stable JSON API exists"
                )
            )
        else:
            self.quota_row.set_subtitle(
                _("Unavailable — official CLI has no account/storage quota command (probed 0.8.0)")
            )

    def _apply_cli_version(self, info: CliVersionInfo) -> None:
        current = info.cli_version or info.app_version or _("Unknown")
        if info.app_version and info.cli_version and info.app_version != info.cli_version:
            current = f"{info.cli_version} ({info.app_version})"
        self.cli_version_row.set_subtitle(current)
        self.cli_update_row.set_subtitle(info.status_line)
        self.cli_update_row.set_tooltip_text(info.raw)
        self._cli_download_url = info.download_url or CLI_DOWNLOAD_URL
        self.cli_download_btn.set_visible(info.update_available)
        self.cli_help_btn.set_visible(info.update_available)
        self.window.version_label.set_text(info.summary())
        self.window.version_label.set_tooltip_text(info.raw)

    def _on_live(self, payload: dict) -> None:
        email = payload.get("email") or ""
        if email:
            self.window.email = email
            self.window.account_label.set_text(email)
        self.email_row.set_subtitle(email or _("Not signed in"))
        self._apply_quota_probe(bool(payload.get("quota_available")))
        info = payload.get("version")
        if isinstance(info, CliVersionInfo):
            self._apply_cli_version(info)
        else:
            parsed = parse_version_output(str(info or ""))
            self._apply_cli_version(parsed)
        self.cli_row.set_subtitle(str(payload.get("path") or self._cli_path_text()))

    def _on_live_error(self, exc: BaseException) -> None:
        if isinstance(exc, NotLoggedIn):
            self.email_row.set_subtitle(_("Not signed in"))
            self._apply_quota_probe(False)
            return
        self.quota_row.set_subtitle(str(exc)[:160])
        self.cli_version_row.set_subtitle(str(exc)[:160])
        self.cli_update_row.set_subtitle(str(exc)[:160])

    def _persist(self, **updates) -> None:
        self.cfg.update(updates)
        save_config(self.cfg)

    def _on_theme(self, row, _pspec) -> None:
        name = ["dark", "light", "system"][int(row.get_selected())]
        self._persist(theme=name)
        apply_theme(name)

    def _on_language(self, row, _pspec) -> None:
        codes = [code for code, _label in language_choices()]
        index = int(row.get_selected())
        if index < 0 or index >= len(codes):
            return
        code = codes[index]
        if normalize_language(self.cfg.get("language")) == code:
            return
        self._persist(language=code)
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.relaunch()

    def _on_autostart(self, row, _pspec) -> None:
        enabled = bool(row.get_active())
        _set_autostart(enabled)
        self._persist(autostart=enabled)

    def _set_systemd_row_active(self, active: bool) -> None:
        self._systemd_switch_guard = True
        self.systemd_row.set_active(active)
        self._systemd_switch_guard = False

    def _apply_systemd_interval_subtitle(self, *, available: bool | None = None) -> None:
        ok = systemd_user_available() if available is None else bool(available)
        if not ok:
            self.systemd_row.set_subtitle(_("systemd --user is not available on this session"))
            return
        seconds = normalize_sync_interval_seconds(self.cfg.get("sync_interval_seconds"))
        self.systemd_row.set_subtitle(
            _(
                "Optional. Runs one always-on pass every {seconds} seconds via systemctl --user, "
                "alongside XDG autostart. Requires a systemd user session. Interval comes from "
                "Always-on folder → Sync interval."
            ).format(seconds=seconds)
        )

    def _on_sync_interval(self, row, _pspec) -> None:
        if self._sync_interval_guard:
            return
        seconds = normalize_sync_interval_seconds(row.get_value())
        if int(row.get_value()) != seconds:
            self._sync_interval_guard = True
            row.set_value(float(seconds))
            self._sync_interval_guard = False
        if seconds == normalize_sync_interval_seconds(self.cfg.get("sync_interval_seconds")):
            return
        self._persist(sync_interval_seconds=seconds)
        self._apply_systemd_interval_subtitle()
        if bool(self.cfg.get("sync_systemd")) and self.systemd_row.get_active():
            result = set_sync_systemd(True, interval_seconds=seconds)
            if not result.get("ok") and result.get("available"):
                detail = str(result.get("message") or _("Could not update systemd timer"))
                self.window._toast(_("systemd timer failed: {error}").format(error=detail[:120]))
            elif result.get("ok"):
                self.window._toast(
                    _("systemd timer interval set to {seconds}s").format(seconds=seconds)
                )

    def _on_sync_pass_timeout_enabled(self, row, _pspec) -> None:
        if self._sync_pass_timeout_guard:
            return
        enabled = bool(row.get_active())
        current = normalize_sync_pass_timeout_seconds(self.cfg.get("sync_pass_timeout_seconds"))
        if enabled:
            seconds = current if current > 0 else SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED
            self._sync_pass_timeout_guard = True
            self.sync_pass_timeout_row.set_sensitive(True)
            self.sync_pass_timeout_row.set_value(float(seconds))
            self._sync_pass_timeout_guard = False
            if seconds != current:
                self._persist(sync_pass_timeout_seconds=seconds)
            return
        self._sync_pass_timeout_guard = True
        self.sync_pass_timeout_row.set_sensitive(False)
        self._sync_pass_timeout_guard = False
        if current != 0:
            self._persist(sync_pass_timeout_seconds=0)

    def _on_sync_pass_timeout(self, row, _pspec) -> None:
        if self._sync_pass_timeout_guard:
            return
        if not self.sync_pass_timeout_switch.get_active():
            return
        seconds = normalize_sync_pass_timeout_seconds(row.get_value())
        if seconds <= 0:
            seconds = SYNC_PASS_TIMEOUT_SECONDS_SUGGESTED
        if int(row.get_value()) != seconds:
            self._sync_pass_timeout_guard = True
            row.set_value(float(seconds))
            self._sync_pass_timeout_guard = False
        if seconds == normalize_sync_pass_timeout_seconds(self.cfg.get("sync_pass_timeout_seconds")):
            return
        self._persist(sync_pass_timeout_seconds=seconds)

    def _on_systemd_sync(self, row, _pspec) -> None:
        if self._systemd_switch_guard:
            return
        enabled = bool(row.get_active())
        if enabled and not systemd_user_available():
            self._set_systemd_row_active(False)
            self.window._toast(_("systemd --user is not available on this session"))
            return
        interval = normalize_sync_interval_seconds(self.cfg.get("sync_interval_seconds"))
        result = set_sync_systemd(enabled, interval_seconds=interval)
        if enabled and not result.get("ok"):
            self._set_systemd_row_active(False)
            self._persist(sync_systemd=False)
            detail = str(result.get("message") or _("Could not enable systemd timer"))
            self.window._toast(_("systemd timer failed: {error}").format(error=detail[:120]))
            return
        self._persist(sync_systemd=bool(enabled and result.get("ok")))
        self._apply_systemd_interval_subtitle()
        if enabled:
            self.window._toast(_("systemd user timer enabled"))
        else:
            self.window._toast(_("systemd user timer disabled"))

    def _set_path_trigger_row_active(self, active: bool) -> None:
        self._path_trigger_guard = True
        self.path_trigger_row.set_active(active)
        self._path_trigger_guard = False

    def _apply_path_trigger_subtitle(
        self,
        *,
        watch_ok: bool | None = None,
        systemd_ok: bool | None = None,
    ) -> None:
        gio_ok = local_watch_available() if watch_ok is None else bool(watch_ok)
        sys_ok = systemd_user_available() if systemd_ok is None else bool(systemd_ok)
        if not gio_ok and not sys_ok:
            self.path_trigger_row.set_subtitle(
                _("Local path watching is not available on this session")
            )
            return
        parts = [
            _(
                "Optional. After edits under the always-on folder, wait {seconds}s then "
                "run a sync pass without waiting for the fixed interval."
            ).format(seconds=PATH_TRIGGER_DEBOUNCE_SECONDS)
        ]
        if gio_ok:
            parts.append(_("Uses recursive inotify while this app is running."))
        if sys_ok:
            parts.append(
                _(
                    "Also installs a systemd --user path unit for the folder root and "
                    "immediate subfolders only (systemd cannot watch deeply nested paths). "
                    "Keep this app open for deep trees, or wait for the sync interval. "
                    "The path unit is rewritten when the always-on folder changes."
                )
            )
        elif not gio_ok:
            parts.append(_("systemd --user is not available; path unit skipped."))
        self.path_trigger_row.set_subtitle(" ".join(parts))

    def _on_path_trigger(self, row, _pspec) -> None:
        if self._path_trigger_guard:
            return
        enabled = bool(row.get_active())
        watch_ok = local_watch_available()
        systemd_ok = systemd_user_available()
        if enabled and not watch_ok and not systemd_ok:
            self._set_path_trigger_row_active(False)
            self.window._toast(_("Local path watching is not available on this session"))
            return
        folder = str(self.cfg.get("sync_folder") or configured_sync_folder())
        Path(folder).expanduser().mkdir(parents=True, exist_ok=True)
        folders = sync_pair_local_paths(self.cfg, enabled_only=True)
        systemd_result: dict | None = None
        if enabled:
            if systemd_ok:
                systemd_result = set_sync_path_trigger(True, folders=folders)
                if not systemd_result.get("ok") and not watch_ok:
                    self._set_path_trigger_row_active(False)
                    self._persist(sync_path_trigger=False)
                    detail = str(
                        systemd_result.get("message") or _("Could not enable path trigger")
                    )
                    self.window._toast(
                        _("Path trigger failed: {error}").format(error=detail[:120])
                    )
                    return
            self._persist(sync_path_trigger=True)
            application = self.window.get_application()
            if isinstance(application, DriveApp):
                application.refresh_path_trigger_watch()
            self._apply_path_trigger_subtitle(watch_ok=watch_ok, systemd_ok=systemd_ok)
            if systemd_result and not systemd_result.get("ok") and watch_ok:
                self.window._toast(
                    _("Path trigger on (inotify only; systemd path unit unavailable)")
                )
            else:
                self.window._toast(_("Sync soon after local edits enabled"))
            return
        if systemd_ok or sync_path_unit_is_enabled() or sync_systemd_path_unit_path().is_file():
            set_sync_path_trigger(False)
        self._persist(sync_path_trigger=False)
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.refresh_path_trigger_watch()
        self._apply_path_trigger_subtitle(watch_ok=watch_ok, systemd_ok=systemd_ok)
        self.window._toast(_("Sync soon after local edits disabled"))

    def _choose_download(self, *_args) -> None:
        dialog = Gtk.FileDialog(title=_("Download folder"))
        dialog.select_folder(self.window, None, self._on_download_chosen)

    def _on_download_chosen(self, dialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if folder is None or not folder.get_path():
            return
        path = folder.get_path()
        self._persist(download_folder=path)
        self.download_row.set_subtitle(path)

    def _choose_sync(self, *_args) -> None:
        dialog = Gtk.FileDialog(title=_("Always-on folder"))
        dialog.select_folder(self.window, None, self._on_sync_chosen)

    def _on_sync_chosen(self, dialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if folder is None or not folder.get_path():
            return
        path = folder.get_path()
        self._persist(sync_folder=path)
        self.sync_folder_row.set_subtitle(path)
        Path(path).mkdir(parents=True, exist_ok=True)
        if bool(self.cfg.get("sync_path_trigger")):
            if systemd_user_available():
                set_sync_path_trigger(True, folders=sync_pair_local_paths(self.cfg, enabled_only=True))
            application = self.window.get_application()
            if isinstance(application, DriveApp):
                application.refresh_path_trigger_watch()
        if bool(self.cfg.get("sync_enabled")):
            self._run_sync_preview(
                confirm_label=_("Sync now"),
                on_confirm=self._start_sync_after_preview,
            )
        self._rebuild_sync_pair_rows()

    def _on_sync_exclude_apply(self, row: Adw.EntryRow) -> None:
        text = str(row.get_text() or "").strip()
        if text == str(self.cfg.get("sync_exclude") or "").strip():
            return
        self._persist(sync_exclude=text)
        if bool(self.cfg.get("sync_enabled")):
            application = self.window.get_application()
            if isinstance(application, DriveApp):
                application.start_sync_now()
                self._apply_activity()

    def _on_sync_remote_apply(self, row: Adw.EntryRow) -> None:
        from .config import normalize_sync_remote_root

        normalized = normalize_sync_remote_root(row.get_text())
        row.set_text(normalized)
        if normalized == str(self.cfg.get("sync_remote_root") or "/my-files"):
            return
        self._persist(sync_remote_root=normalized)
        if bool(self.cfg.get("sync_enabled")):
            self._run_sync_preview(
                confirm_label=_("Sync now"),
                on_confirm=self._start_sync_after_preview,
            )

    def _on_sync_conflict_policy(self, row, _pspec) -> None:
        policy = "rename" if int(row.get_selected()) == 1 else "skip"
        if policy == normalize_sync_conflict_policy(self.cfg.get("sync_conflict_policy")):
            return
        self._persist(sync_conflict_policy=policy)
        if bool(self.cfg.get("sync_enabled")):
            application = self.window.get_application()
            if isinstance(application, DriveApp):
                application.start_sync_now()
                self._apply_activity()

    def _on_sync_direction(self, row, _pspec) -> None:
        index = int(row.get_selected())
        direction = ("bidirectional", "upload-only", "download-only")[index] if 0 <= index <= 2 else "bidirectional"
        if direction == normalize_sync_direction(self.cfg.get("sync_direction")):
            return
        self._persist(sync_direction=direction)
        if bool(self.cfg.get("sync_enabled")):
            application = self.window.get_application()
            if isinstance(application, DriveApp):
                application.start_sync_now()
                self._apply_activity()

    def _set_sync_switch_active(self, active: bool) -> None:
        self._sync_switch_guard = True
        self.sync_switch.set_active(active)
        self._sync_switch_guard = False

    def _run_sync_preview(
        self,
        *,
        confirm_label: str,
        on_confirm,
        offer_seed: bool = False,
    ) -> None:
        """List remote + local children and show counts before enable or path-change sync."""
        if self._sync_preview_busy:
            return
        self._sync_preview_busy = True
        Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(parents=True, exist_ok=True)
        self.sync_worker_row.set_subtitle(_("Previewing…"))
        cfg = dict(self.cfg)

        def work():
            return preview_pass(cfg=cfg, cli=self.window.cli)

        def done(preview: dict) -> None:
            self._sync_preview_busy = False
            self._apply_activity()
            downloads = int(preview.get("download_count") or 0)
            uploads = int(preview.get("upload_count") or 0)
            self.sync_files_row.set_subtitle(
                _("Preview: {pull} remote, {push} local").format(pull=downloads, push=uploads)
            )
            dialog = Adw.MessageDialog(
                transient_for=self.window,
                heading=_("Always-on folder preview"),
                body=format_preview_message(preview, offer_seed=offer_seed),
            )
            dialog.add_response("cancel", _("Cancel"))
            if offer_seed:
                dialog.add_response("seed", _("Assume already synced"))
            dialog.add_response("confirm", confirm_label)
            dialog.set_default_response("confirm")
            dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect(
                "response",
                self._on_sync_preview_response,
                on_confirm,
                offer_seed,
            )
            dialog.present()

        def failed(exc: BaseException) -> None:
            self._sync_preview_busy = False
            self._apply_activity()
            if isinstance(exc, NotLoggedIn):
                self.window._toast(_("Sign in required for always-on preview"))
            else:
                self.window._toast(_("Always-on preview failed: {error}").format(error=str(exc)[:120]))

        self.window._bg(work, done, failed)

    def _on_sync_preview_response(
        self,
        _dialog,
        response: str,
        on_confirm,
        offer_seed: bool = False,
    ) -> None:
        if response == "seed" and offer_seed:
            self._seed_then_enable()
            return
        if response != "confirm":
            self._apply_activity()
            return
        on_confirm()

    def _enable_sync_after_preview(self) -> None:
        Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(parents=True, exist_ok=True)
        _set_autostart(True)
        self._persist(sync_enabled=True, autostart=True, sync_paused=False)
        self._set_sync_switch_active(True)
        self._set_sync_pause_row_active(False)
        self.sync_pause_row.set_sensitive(True)
        if not self.autostart_row.get_active():
            self.autostart_row.set_active(True)
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.refresh_path_trigger_watch()
            application.start_sync_now()
            application._refresh_sync_label()
            if application._tray is not None:
                application._tray.set_sync_paused(False, enabled=True)
        self._apply_activity()

    def _seed_then_enable(self) -> None:
        """Seed delta fingerprints, then enable always-on without a bulk first pass."""
        if self._sync_preview_busy:
            return
        self._sync_preview_busy = True
        Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(
            parents=True, exist_ok=True
        )
        self.sync_worker_row.set_subtitle(_("Seeding…"))
        cfg = dict(self.cfg)

        def work():
            return seed_sync_delta(cfg=cfg, cli=self.window.cli)

        def done(result: dict) -> None:
            self._sync_preview_busy = False
            self._enable_sync_after_preview()
            self.window._toast(format_seed_message(result))

        def failed(exc: BaseException) -> None:
            self._sync_preview_busy = False
            self._apply_activity()
            if isinstance(exc, NotLoggedIn):
                self.window._toast(_("Sign in required to assume already synced"))
            else:
                self.window._toast(
                    _("Assume already synced failed: {error}").format(error=str(exc)[:120])
                )

        self.window._bg(work, done, failed)

    def _on_sync_seed(self, *_args) -> None:
        """Explicit Settings control: seed delta from current local+remote state."""
        if self._sync_preview_busy:
            return
        self._sync_preview_busy = True
        Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(
            parents=True, exist_ok=True
        )
        self.sync_worker_row.set_subtitle(_("Seeding…"))
        cfg = dict(self.cfg)

        def work():
            return seed_sync_delta(cfg=cfg, cli=self.window.cli)

        def done(result: dict) -> None:
            self._sync_preview_busy = False
            self._apply_activity()
            self.window._toast(format_seed_message(result))

        def failed(exc: BaseException) -> None:
            self._sync_preview_busy = False
            self._apply_activity()
            if isinstance(exc, NotLoggedIn):
                self.window._toast(_("Sign in required to assume already synced"))
            else:
                self.window._toast(
                    _("Assume already synced failed: {error}").format(error=str(exc)[:120])
                )

        self.window._bg(work, done, failed)

    def _start_sync_after_preview(self) -> None:
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.start_sync_now()
            application._refresh_sync_label()
        self._apply_activity()

    def _on_sync_enabled(self, row, _pspec) -> None:
        if self._sync_switch_guard:
            return
        enabled = bool(row.get_active())
        application = self.window.get_application()
        if enabled:
            # Revert until the dry-run preview is confirmed (or assume-synced).
            self._set_sync_switch_active(False)
            self._run_sync_preview(
                confirm_label=_("Enable"),
                on_confirm=self._enable_sync_after_preview,
                offer_seed=True,
            )
            return
        self._persist(sync_enabled=False)
        if isinstance(application, DriveApp):
            application._stop_sync_worker()
            application.refresh_path_trigger_watch()
            application._refresh_sync_label()
            if application._tray is not None:
                application._tray.set_sync_paused(False, enabled=False)
        mark_worker_stopped()
        self._set_sync_pause_row_active(False)
        self.sync_pause_row.set_sensitive(False)
        self._apply_activity()

    def _sync_now(self, *_args) -> None:
        Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(parents=True, exist_ok=True)
        if not bool(self.cfg.get("sync_enabled")):
            # Triggers dry-run preview via _on_sync_enabled, then enables.
            self.sync_switch.set_active(True)
            return
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.start_sync_now()
        self._apply_activity()

    def _apply_activity(self) -> None:
        snap = activity_snapshot()
        worker = str(snap["worker"])
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            proc = application._sync_proc
            if snap["enabled"] and not snap.get("paused") and proc is not None and proc.poll() is None and not snap["running"]:
                worker = _("Running (pid {pid})").format(pid=proc.pid)
            application._refresh_sync_label()
        self.sync_worker_row.set_subtitle(worker)
        self.sync_last_pass_row.set_subtitle(str(snap["last_success"]))
        files = str(snap["files"])
        if snap.get("last_timeout"):
            files = _("{files}; last pass timed out").format(files=files)
        self.sync_files_row.set_subtitle(files)
        self.sync_error_row.set_subtitle(str(snap["last_error"]))
        history_lines = list(snap.get("history_lines") or [])
        if history_lines:
            self.sync_history_row.set_subtitle("\n".join(history_lines[:8]))
        else:
            self.sync_history_row.set_subtitle(_("No history yet"))
        self.sync_pause_row.set_sensitive(bool(snap.get("enabled")))

    def _on_sync_paused(self, row, _pspec) -> None:
        if self._sync_pause_guard:
            return
        paused = bool(row.get_active())
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.set_sync_paused(paused)
        else:
            self._persist(sync_paused=paused)
        self.cfg = load_config()
        self._apply_activity()

    def _set_sync_pause_row_active(self, active: bool) -> None:
        self._sync_pause_guard = True
        self.sync_pause_row.set_active(active)
        self._sync_pause_guard = False

    def _rebuild_sync_pair_rows(self) -> None:
        for row in getattr(self, "_sync_pair_rows", []):
            self._sync_pairs_group.remove(row)
        self._sync_pair_rows = []
        pairs = ensure_sync_pairs(self.cfg)
        for index, pair in enumerate(pairs):
            local = str(pair.get("local_path") or "")
            remote = str(pair.get("remote_root") or "/my-files")
            title = _("Pair {n}").format(n=index + 1)
            if index == 0:
                title = _("Primary pair")
            row = Adw.ActionRow(
                title=title,
                subtitle=f"{local} ↔ {remote}",
            )
            enabled = Gtk.Switch(valign=Gtk.Align.CENTER)
            enabled.set_active(bool(pair.get("enabled", True)))
            enabled.connect("notify::active", self._on_pair_enabled, pair.get("id"))
            row.add_suffix(enabled)
            if index > 0:
                remove_btn = Gtk.Button(label=_("Remove"), valign=Gtk.Align.CENTER)
                remove_btn.connect("clicked", self._on_remove_sync_pair, pair.get("id"))
                row.add_suffix(remove_btn)
            edit_btn = Gtk.Button(label=_("Edit"), valign=Gtk.Align.CENTER)
            edit_btn.connect("clicked", self._on_edit_sync_pair, pair.get("id"))
            row.add_suffix(edit_btn)
            self._sync_pairs_group.add(row)
            self._sync_pair_rows.append(row)

    def _pairs_from_cfg(self) -> list[dict]:
        return ensure_sync_pairs(self.cfg)

    def _save_pairs(self, pairs: list[dict]) -> None:
        self._persist(sync_pairs=pairs)
        self.cfg = load_config()
        self.sync_folder_row.set_subtitle(str(self.cfg.get("sync_folder") or ""))
        self.sync_remote_row.set_text(str(self.cfg.get("sync_remote_root") or "/my-files"))
        self.sync_exclude_row.set_text(str(self.cfg.get("sync_exclude") or ""))
        self._rebuild_sync_pair_rows()
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.refresh_path_trigger_watch()
            if bool(self.cfg.get("sync_path_trigger")) and systemd_user_available():
                set_sync_path_trigger(True, folders=sync_pair_local_paths(self.cfg, enabled_only=True))

    def _on_pair_enabled(self, switch, _pspec, pair_id: str) -> None:
        pairs = self._pairs_from_cfg()
        for pair in pairs:
            if pair.get("id") == pair_id:
                pair["enabled"] = bool(switch.get_active())
                break
        self._save_pairs(pairs)

    def _on_remove_sync_pair(self, _btn, pair_id: str) -> None:
        pairs = [pair for pair in self._pairs_from_cfg() if pair.get("id") != pair_id]
        if not pairs:
            pairs = [empty_sync_pair(pair_id="default")]
        self._save_pairs(pairs)
        self.window._toast(_("Sync pair removed"))

    def _on_add_sync_pair(self, *_args) -> None:
        self._edit_sync_pair_dialog(None)

    def _on_edit_sync_pair(self, _btn, pair_id: str) -> None:
        pairs = self._pairs_from_cfg()
        target = next((pair for pair in pairs if pair.get("id") == pair_id), None)
        self._edit_sync_pair_dialog(target)

    def _edit_sync_pair_dialog(self, pair: dict | None) -> None:
        creating = pair is None
        current = dict(pair) if pair is not None else empty_sync_pair()
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=_("Add sync pair") if creating else _("Edit sync pair"),
            body=_("Local folder and remote /my-files path for this pair."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_default_response("save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        local_entry = Gtk.Entry()
        local_entry.set_placeholder_text(_("Local folder path"))
        local_entry.set_text(str(current.get("local_path") or ""))
        remote_entry = Gtk.Entry()
        remote_entry.set_placeholder_text("/my-files/…")
        remote_entry.set_text(str(current.get("remote_root") or "/my-files"))
        exclude_entry = Gtk.Entry()
        exclude_entry.set_placeholder_text(_("Exclude patterns (optional)"))
        exclude_entry.set_text(str(current.get("exclude") or ""))
        box.append(Gtk.Label(label=_("Local folder"), xalign=0))
        box.append(local_entry)
        box.append(Gtk.Label(label=_("Remote root"), xalign=0))
        box.append(remote_entry)
        box.append(Gtk.Label(label=_("Exclude"), xalign=0))
        box.append(exclude_entry)
        dialog.set_extra_child(box)

        def on_response(_dialog, response: str) -> None:
            if response != "save":
                return
            local = str(local_entry.get_text() or "").strip()
            remote = normalize_sync_remote_root(remote_entry.get_text())
            if not local:
                self.window._toast(_("Local folder is required"))
                return
            Path(local).expanduser().mkdir(parents=True, exist_ok=True)
            updated = empty_sync_pair(
                pair_id=str(current.get("id") or ""),
                local_path=local,
                remote_root=remote,
                enabled=bool(current.get("enabled", True)),
                exclude=str(exclude_entry.get_text() or ""),
                conflict_policy=current.get("conflict_policy") or self.cfg.get("sync_conflict_policy"),
                direction=current.get("direction") or self.cfg.get("sync_direction"),
            )
            pairs = self._pairs_from_cfg()
            if creating:
                pairs.append(updated)
            else:
                for index, item in enumerate(pairs):
                    if item.get("id") == updated["id"]:
                        pairs[index] = updated
                        break
                else:
                    pairs.append(updated)
            self._save_pairs(pairs)
            self.window._toast(_("Sync pair saved"))

        dialog.connect("response", on_response)
        dialog.present()

    def _on_activity_tick(self) -> bool:
        if not self._activity_alive:
            self._activity_source = 0
            return False
        self._apply_activity()
        if not self._activity_alive:
            self._activity_source = 0
            return False
        return True

    def _on_settings_closed(self, *_args) -> None:
        self._activity_alive = False
        source = getattr(self, "_activity_source", 0) or 0
        if source:
            GLib.source_remove(source)
            self._activity_source = 0

    def _choose_cli(self, *_args) -> None:
        dialog = Gtk.FileDialog(title=_("Official proton-drive binary"))
        dialog.open(self.window, None, self._on_cli_chosen)

    def _on_cli_chosen(self, dialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is None or not file.get_path():
            return
        path = file.get_path()
        if not Path(path).is_file():
            return
        self._persist(cli_path=path)
        self.window.cli = ProtonDriveCli(path)
        self.cli_row.set_subtitle(path)
        self.window._bg(self.window.cli.version_info, self._apply_cli_version)
        self.window._bg(
            lambda: verify_proton_drive_binary(path, force=True),
            self._on_cli_checksum,
            lambda *_: None,
        )

    def _sign_out(self, *_args) -> None:
        def work():
            self.window.cli.logout()
            return True

        def done(_ok) -> None:
            self.window.email = ""
            self.email_row.set_subtitle(_("Not signed in"))
            self.window.account_label.set_text(_("Not signed in"))
            self.window.reload()
            self.close()

        self.window._bg(work, done)


def main() -> int:
    from .i18n import install as install_i18n

    install_i18n()
    Adw.init()
    apply_gtk_direction()
    os.environ.setdefault("ADW_DISABLE_PORTAL", "0")
    apply_theme()
    app = DriveApp()
    return app.run()
