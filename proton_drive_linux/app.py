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
    account_email,
    added_by_email,
    album_cli_path,
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
    apply_theme,
    download_folder,
    load as load_config,
    save as save_config,
    set_gui_busy,
    sync_folder as configured_sync_folder,
)
from .i18n import _, language_choices, ngettext, normalize_language
from .sync import activity_snapshot, due_for_pass, format_status_line, mark_worker_idle, mark_worker_stopped, spawn_worker
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
    xdg_autostart_path,
)
from .tray import StatusNotifierTray
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
        self.set_default_size(1180, 760)
        self.cli = ProtonDriveCli()
        self.section = "/my-files"
        self.current_path = "/my-files"
        self.crumbs: list[tuple[str, str]] = [(_("My files"), "/my-files")]
        self.busy = False
        self.email = ""
        self.store = Gio.ListStore.new(DriveItem)
        self._timeline_cache: list | None = None
        self.set_icon_name(APP_ICON_NAME)
        self._build()
        self.reload()

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
        self.side_list.select_row(self.side_list.get_row_at_index(0))
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
        self.path_title = Adw.WindowTitle(title=_("My files"), subtitle="/my-files")
        header.set_title_widget(self.path_title)

        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=_("Back"))
        self.back_btn.connect("clicked", lambda *_: self._go_up())
        header.pack_start(self.back_btn)

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

        self.status = Gtk.Label(xalign=0, margin_start=16, margin_end=16, margin_top=6, margin_bottom=6, css_classes=["dim-label"])
        content_toolbar.add_bottom_bar(self.status)

        self.stack = Gtk.Stack()
        self.spinner = Gtk.Spinner()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, spacing=12)
        loading.append(self.spinner)
        loading.append(Gtk.Label(label=_("Loading Proton Drive…")))
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
        self.column = Gtk.ColumnView(model=Gtk.SingleSelection(model=self.store), show_column_separators=False, show_row_separators=True)
        self.column.connect("activate", self._on_activate)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.column.add_controller(keys)
        right_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right_click.connect("pressed", self._on_item_context)
        self.column.add_controller(right_click)
        self._item_popover: Gtk.Popover | None = None
        self._add_column(_("Name"), self._name_setup, self._name_bind, expand=True)
        self._add_column(_("Modified"), self._label_setup, self._modified_bind, width=170)
        self._add_column(_("Size"), self._label_setup, self._size_bind, width=110)
        scrolled.set_child(self.column)
        self.stack.add_named(scrolled, "list")
        content_toolbar.set_content(self.stack)
        split.set_content(content_page)

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
        media = str(item.node.get("mediaType") or "")
        if item.kind == "folder":
            icon = "folder"
        elif item.kind == "invitation":
            icon = "mail-unread-symbolic"
        elif item.kind in ("day", "album"):
            icon = "folder-pictures"
        elif item.kind == "photo" and media.startswith("video"):
            icon = "video-x-generic"
        elif item.kind == "photo":
            icon = "image-x-generic"
        else:
            icon = "text-x-generic"
        image.set_from_icon_name(icon)
        label.set_text(item.name)
        label.set_tooltip_text(item.path)

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
            self.status.set_text(message or _("Working…"))

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
        self.reload()

    def _go_up(self) -> None:
        if len(self.crumbs) < 2:
            return
        self.crumbs.pop()
        self.current_path = self.crumbs[-1][1]
        self.reload()

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
        self._set_busy(True, _("Reading {path}").format(path=path))
        self.path_title.set_title(self.crumbs[-1][0])
        self.path_title.set_subtitle(path)
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
            self._bg(lambda: self._load_photos(path, cache), self._on_photos)
            return
        self._bg(lambda: self._load_files(path), self._on_list)

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
            self.status.set_text(_item_count(0))
            return
        self.empty.set_title(_("This folder is empty"))
        self.empty.set_description(_("Upload files with the official Proton Drive CLI session on this machine."))
        self.stack.set_visible_child_name("list")
        extra = ngettext("{count} photo", "{count} photos", len(timeline)).format(count=len(timeline)) if kind == "root" else (self.email or "Proton Drive")
        self.status.set_text(_("{count} · {extra}").format(count=_item_count(count), extra=extra))

    def _load_files(self, path: str) -> tuple[list, list]:
        nodes = self.cli.list(path)
        invitations: list = []
        if path.rstrip("/") == "/shared-with-me":
            invitations = self.cli.invitation_list()
        return nodes, invitations

    def _on_list(self, payload) -> None:
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
            self.status.set_text(_item_count(0))
            return
        self.empty.set_title(_("This folder is empty"))
        self.empty.set_description(_("Upload files with the official Proton Drive CLI session on this machine."))
        self.stack.set_visible_child_name("list")
        pending = ""
        if invitations:
            pending = _(" · {count} invitation(s)").format(count=len(invitations))
        self.status.set_text(_("{count} · {extra}").format(count=_item_count(count), extra=f"{self.email or 'Proton Drive'}{pending}"))

    def _selected(self) -> DriveItem | None:
        selection = self.column.get_model()
        if not isinstance(selection, Gtk.SingleSelection):
            return None
        item = selection.get_selected_item()
        return item if isinstance(item, DriveItem) else None

    def _open_selected(self, *_args) -> None:
        selection = self.column.get_model()
        if isinstance(selection, Gtk.SingleSelection):
            self._on_activate(self.column, selection.get_selected())

    def _on_key(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._open_selected()
            return True
        if keyval == Gdk.KEY_F2:
            self._rename()
            return True
        return False

    def _on_item_context(self, _gesture, _n_press, x, y) -> None:
        item = self._selected()
        if item is None:
            self._toast(_("Select an item first"))
            return
        if self._item_popover is not None:
            self._item_popover.popdown()
            self._item_popover.unparent()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        if self.section == "/trash":
            actions = [
                (_("Restore"), self._trash),
                (_("Delete permanently"), self._delete_permanently),
                (_("Empty trash"), self._empty_trash),
            ]
        elif self.section == "/photos":
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
        popover = Gtk.Popover()
        for label, handler in actions:
            btn = Gtk.Button(label=label, has_frame=False)
            child = btn.get_child()
            if isinstance(child, Gtk.Label):
                child.set_xalign(0)
            btn.connect("clicked", lambda _b, h=handler, p=popover: (p.popdown(), h()))
            box.append(btn)
        popover.set_child(box)
        popover.set_parent(self.column)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        self._item_popover = popover
        popover.popup()

    def _on_activate(self, _view, position: int) -> None:
        item = self.store.get_item(position)
        if not isinstance(item, DriveItem):
            return
        if item.kind in ("folder", "day", "album"):
            self.crumbs.append((item.name, item.path))
            self.current_path = item.path
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
        if not paths:
            return
        parent = self.current_path
        self._set_busy(True, ngettext("Uploading {count} item", "Uploading {count} items", len(paths)).format(count=len(paths)))
        if self.section == "/photos":
            self._bg(lambda: self.cli.photo_upload(paths), lambda *_: (self._toast(_("Upload finished")), self.reload()))
            return
        self._bg(lambda: self.cli.upload(paths, parent), lambda *_: (self._toast(_("Upload finished")), self.reload()))

    def _download(self, *_args) -> None:
        item = self._selected()
        if item is None:
            self._toast(_("Select a file or folder first"))
            return
        self._download_item(item)

    def _download_item(self, item: DriveItem) -> None:
        if item.kind in ("day", "album"):
            self._toast(_("Open a day or album, then select a photo"))
            return
        if item.kind == "invitation":
            InvitationDialog(self, item).present()
            return
        dest = str(download_folder())
        self._set_busy(True, _("Downloading {name}").format(name=item.name))

        def work():
            if item.kind == "photo" or self.section == "/photos":
                self.cli.photo_download(item.path, dest)
            else:
                self.cli.download(item.path, dest)
            return dest

        def done(folder: str) -> None:
            self._toast(_("Saved to {folder}").format(folder=folder))
            self.reload()
            subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self._bg(work, done)

    def _trash(self, *_args) -> None:
        item = self._selected()
        if item is None:
            self._toast(_("Select an item first"))
            return
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

    def _mutate_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._toast(str(exc)[:180])

    def _file_op_item(self) -> DriveItem | None:
        item = self._selected()
        if item is None:
            self._toast(_("Select a file or folder first"))
            return None
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
        item = self._file_op_item()
        if item is None:
            return
        DestinationDialog(self, item, "move").present(self)

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
    def __init__(self, window: DriveWindow, item: DriveItem, action: str) -> None:
        super().__init__()
        self.window = window
        self.item = item
        self.action = action
        self.dest_path = window._default_dest()
        verb = _("Copy") if action == "copy" else _("Move")
        self.set_title(_("{verb} {name}").format(verb=verb, name=item.name))
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
        page.append(Gtk.Label(label=_("{verb} \"{name}\" into a folder. Click a folder to open it.").format(verb=verb, name=item.name), xalign=0, wrap=True, css_classes=["dim-label"]))
        roots = Gtk.DropDown.new_from_strings([_("My files"), _("Shared with me")])
        roots.set_selected(0)
        roots.connect("notify::selected", self._on_root)
        page.append(roots)
        self.root_drop = roots
        if action == "copy":
            self.name_entry = Gtk.Entry(text=item.name, placeholder_text=_("Name of the copy"))
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
        for node in folders:
            name = node_name(node)
            path = join_path(self.dest_path, name)
            if path == self.item.path:
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
        source = self.item.path
        if dest == source:
            self.window._toast(_("Choose a different folder"))
            return
        name = None
        if self.name_entry is not None:
            name = self.name_entry.get_text().strip() or None
            if name == self.item.name:
                name = None
        window = self.window
        action = self.action
        self.close()

        def work():
            if action == "copy":
                window.cli.copy(source, dest, name=name)
            else:
                window.cli.move(source, dest)

        def done(_result) -> None:
            verb = _("Copied") if action == "copy" else _("Moved")
            window._toast(_("{verb} to {dest}").format(verb=verb, dest=dest))
            window.reload()

        busy = _("Copying {name}").format(name=self.item.name) if action == "copy" else _("Moving {name}").format(name=self.item.name)
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
        self.app_menu = self._build_app_menu()
        self._install_actions()
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _build_app_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        settings = Gio.Menu()
        settings.append(_("Settings"), "app.preferences")
        settings.append(_("Open Drive in browser"), "app.open-browser")
        settings.append(_("Open always-on folder"), "app.open-sync")
        menu.append_section(None, settings)
        help_section = Gio.Menu()
        help_section.append(_("Proton Drive Help"), "app.help")
        help_section.append(_("Drive CLI Help"), "app.cli-help")
        help_section.append(_("Open CLI logs"), "app.logs")
        menu.append_section(None, help_section)
        about = Gio.Menu()
        about.append(_("About Proton Drive Linux"), "app.about")
        menu.append_section(None, about)
        quit_section = Gio.Menu()
        quit_section.append(_("Quit"), "app.quit")
        menu.append_section(None, quit_section)
        return menu

    def _install_actions(self) -> None:
        actions = {
            "preferences": self._on_preferences,
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
            )
            self._tray.start()
            GLib.timeout_add_seconds(20, self._on_sync_tick)
            if load_config().get("sync_enabled"):
                self._sync_proc = spawn_worker(force=False)
        self._window.present()

    def _on_window_close(self, *_args) -> bool:
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
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def quit_from_tray(self) -> None:
        self._allow_quit = True
        self._stop_sync_worker()
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self.quit()

    def _on_shutdown(self, *_args) -> None:
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
        if self._sync_proc is not None and self._sync_proc.poll() is None:
            return True
        idle = self._window is None or not self._window.busy
        if not idle:
            return True
        if not due_for_pass():
            return True
        self._sync_proc = spawn_worker(force=False)
        return True

    def start_sync_now(self) -> None:
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

    def _on_open_sync(self, *_args) -> None:
        folder = configured_sync_folder()
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
            application_name="Proton Drive Linux",
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
    command = shutil.which("proton-drive-linux") or str(repo_root() / "scripts" / "proton-drive-linux")
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
            subtitle=_("Same as Proton Drive on Windows: System default follows the OS locale; English forces this app’s English catalog. Changing language restarts the app."),
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
            description=_("Official CLI 0.8.0 cannot FUSE-mount Drive and has no Activity log. Enable keeps a real local directory in skip/merge sync with /my-files via a niced filesystem download/upload worker, starts that worker now, and turns on session autostart so it stays on after login. Existing files are never replaced. Worker, last pass, and errors below come from this app's worker lock and ~/.config/proton-drive-linux/sync-status.json."),
        )
        self.sync_switch = Adw.SwitchRow(
            title=_("Enable always-on folder"),
            subtitle=_("Starts the CLI worker now and with this session. Not a kernel mount."),
        )
        self.sync_switch.set_active(bool(self.cfg.get("sync_enabled")))
        self.sync_switch.connect("notify::active", self._on_sync_enabled)
        sync.add(self.sync_switch)
        self.sync_folder_row = Adw.ActionRow(title=_("Folder"), subtitle=str(self.cfg.get("sync_folder") or configured_sync_folder()))
        choose_sync = Gtk.Button(label=_("Choose"), valign=Gtk.Align.CENTER)
        choose_sync.connect("clicked", self._choose_sync)
        self.sync_folder_row.add_suffix(choose_sync)
        open_sync = Gtk.Button(label=_("Open"), valign=Gtk.Align.CENTER)
        open_sync.connect("clicked", lambda *_: window.get_application()._on_open_sync())
        self.sync_folder_row.add_suffix(open_sync)
        sync.add(self.sync_folder_row)
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
        app_page.add(sync)
        self._activity_alive = True
        self._activity_source = GLib.timeout_add_seconds(2, self._on_activity_tick)
        self.connect("closed", self._on_settings_closed)
        self._apply_activity()

        startup = Adw.PreferencesGroup(
            title=_("Startup"),
            description=_("XDG autostart for this GUI. Enabling the always-on folder turns this on so the worker comes back after login."),
        )
        self.autostart_row = Adw.SwitchRow(title=_("Start with this session"))
        self.autostart_row.set_active(xdg_autostart_path().is_file())
        self.autostart_row.connect("notify::active", self._on_autostart)
        startup.add(self.autostart_row)
        app_page.add(startup)

        window._bg(self._load_live, self._on_live, self._on_live_error)

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
        return {"email": email, "version": cli.version_info(), "path": find_binary()}

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
            return
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
        if bool(self.cfg.get("sync_enabled")):
            application = self.window.get_application()
            if isinstance(application, DriveApp):
                application.start_sync_now()
                self._apply_activity()

    def _on_sync_enabled(self, row, _pspec) -> None:
        enabled = bool(row.get_active())
        application = self.window.get_application()
        if enabled:
            Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(parents=True, exist_ok=True)
            _set_autostart(True)
            self._persist(sync_enabled=True, autostart=True)
            if not self.autostart_row.get_active():
                self.autostart_row.set_active(True)
            if isinstance(application, DriveApp):
                application.start_sync_now()
                application._refresh_sync_label()
            self._apply_activity()
            return
        self._persist(sync_enabled=False)
        if isinstance(application, DriveApp):
            application._stop_sync_worker()
            application._refresh_sync_label()
        mark_worker_stopped()
        self._apply_activity()

    def _sync_now(self, *_args) -> None:
        Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(parents=True, exist_ok=True)
        self.sync_switch.set_active(True)
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
            if snap["enabled"] and proc is not None and proc.poll() is None and not snap["running"]:
                worker = _("Running (pid {pid})").format(pid=proc.pid)
            application._refresh_sync_label()
        self.sync_worker_row.set_subtitle(worker)
        self.sync_last_pass_row.set_subtitle(str(snap["last_success"]))
        self.sync_files_row.set_subtitle(str(snap["files"]))
        self.sync_error_row.set_subtitle(str(snap["last_error"]))

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
    os.environ.setdefault("ADW_DISABLE_PORTAL", "0")
    apply_theme()
    app = DriveApp()
    return app.run()
