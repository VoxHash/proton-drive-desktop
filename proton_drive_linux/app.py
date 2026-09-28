"""GTK4 / libadwaita desktop UI for the official Proton Drive CLI."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
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
    NotLoggedIn,
    ProtonDriveCli,
    account_email,
    added_by_email,
    find_binary,
    format_size,
    invitation_name,
    invitation_uid,
    join_path,
    member_email,
    member_role,
    node_name,
    node_size,
)
from .config import (
    apply_theme,
    download_folder,
    load as load_config,
    save as save_config,
    set_gui_busy,
    sync_folder as configured_sync_folder,
)
from .sync import due_for_pass, format_status_line, spawn_worker
from .paths import (
    ACCOUNT_URL,
    APP_ICON_NAME,
    APP_ID,
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
SECTIONS = (
    ("My files", "/my-files", "folder-documents-symbolic"),
    ("Photos", "/photos", "folder-pictures-symbolic"),
    ("Shared with me", "/shared-with-me", "system-users-symbolic"),
    ("Trash", "/trash", "user-trash-symbolic"),
)
_UNSHAREABLE_ROOTS = {"/my-files", "/photos", "/shared-with-me", "/trash"}
_INVITE_ROLES = ("viewer", "editor", "admin")
_LINK_ROLES = ("viewer", "editor")


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


class DriveWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Proton Drive")
        self.set_default_size(1180, 760)
        self.cli = ProtonDriveCli()
        self.section = "/my-files"
        self.current_path = "/my-files"
        self.crumbs: list[tuple[str, str]] = [("My files", "/my-files")]
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

        sidebar_page = Adw.NavigationPage(title="Proton Drive")
        sidebar_toolbar = Adw.ToolbarView()
        sidebar_page.set_child(sidebar_toolbar)
        side_header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Proton Drive", subtitle="Linux · official CLI")
        side_header.set_title_widget(title)
        sidebar_toolbar.add_top_bar(side_header)

        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.side_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["navigation-sidebar"])
        self.side_list.connect("row-activated", self._on_section)
        for label, path, icon in SECTIONS:
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
            label="Checking session…",
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

        content_page = Adw.NavigationPage(title="Files")
        content_toolbar = Adw.ToolbarView()
        content_page.set_child(content_toolbar)
        header = Adw.HeaderBar()
        self.path_title = Adw.WindowTitle(title="My files", subtitle="/my-files")
        header.set_title_widget(self.path_title)

        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back")
        self.back_btn.connect("clicked", lambda *_: self._go_up())
        header.pack_start(self.back_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu", primary=True)
        application = self.get_application()
        if isinstance(application, DriveApp):
            menu_btn.set_menu_model(application.app_menu)
        header.pack_end(menu_btn)

        self.trash_btn: Gtk.Button | None = None
        self.empty_trash_btn: Gtk.Button | None = None
        for icon, tip, handler, key in (
            ("folder-new-symbolic", "New folder", self._new_folder, None),
            ("document-save-symbolic", "Upload", self._upload, None),
            ("folder-download-symbolic", "Download", self._download, None),
            ("emblem-shared-symbolic", "Share or invitations", self._share, None),
            ("document-edit-symbolic", "Rename", self._rename, None),
            ("edit-copy-symbolic", "Copy", self._copy, None),
            ("send-to-symbolic", "Move", self._move, None),
            ("document-open-symbolic", "Open", self._open_selected, None),
            ("user-trash-symbolic", "Move to trash", self._trash, "trash_btn"),
            ("user-trash-full-symbolic", "Empty trash", self._empty_trash, "empty_trash_btn"),
            ("view-refresh-symbolic", "Refresh", lambda *_: self.reload(), None),
        ):
            btn = Gtk.Button(icon_name=icon, tooltip_text=tip)
            btn.connect("clicked", handler)
            header.pack_end(btn)
            if key:
                setattr(self, key, btn)
        if self.empty_trash_btn is not None:
            self.empty_trash_btn.set_visible(False)

        self.login_btn = Gtk.Button(label="Sign in", css_classes=["suggested-action"], visible=False)
        self.login_btn.connect("clicked", self._login)
        header.pack_end(self.login_btn)

        content_toolbar.add_top_bar(header)

        self.status = Gtk.Label(xalign=0, margin_start=16, margin_end=16, margin_top=6, margin_bottom=6, css_classes=["dim-label"])
        content_toolbar.add_bottom_bar(self.status)

        self.stack = Gtk.Stack()
        self.spinner = Gtk.Spinner()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, spacing=12)
        loading.append(self.spinner)
        loading.append(Gtk.Label(label="Loading Proton Drive…"))
        self.stack.add_named(loading, "loading")

        self.empty = Adw.StatusPage(
            icon_name="folder-symbolic",
            title="This folder is empty",
            description="Upload files with the official Proton Drive CLI session on this machine.",
        )
        self.stack.add_named(self.empty, "empty")

        self.error_page = Adw.StatusPage(icon_name="dialog-error-symbolic", title="Could not load Drive")
        signin = Gtk.Button(label="Sign in with Proton", css_classes=["suggested-action", "pill"], halign=Gtk.Align.CENTER)
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
        self._add_column("Name", self._name_setup, self._name_bind, expand=True)
        self._add_column("Modified", self._label_setup, self._modified_bind, width=170)
        self._add_column("Size", self._label_setup, self._size_bind, width=110)
        scrolled.set_child(self.column)
        self.stack.add_named(scrolled, "list")
        content_toolbar.set_content(self.stack)
        split.set_content(content_page)

        self._bg(self.cli.version, self._on_version, self._on_version_error)

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
            text = "Folder"
        elif item.kind == "invitation":
            text = member_role(item.node).title()
        elif item.kind == "day":
            count = int(item.node.get("count") or 0)
            text = f"{count} items"
        elif item.kind == "album":
            text = "Album"
        else:
            text = format_size(item.size)
        list_item.get_child().set_text(text)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        set_gui_busy(busy)
        self.spinner.set_spinning(busy)
        if busy:
            self.stack.set_visible_child_name("loading")
            self.status.set_text(message or "Working…")

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
            self.error_page.set_title("Sign in required")
            self.error_page.set_description("Use the same Proton browser login as the official CLI. Session is stored in the system keyring.")
            self.stack.set_visible_child_name("error")
            self.login_btn.set_visible(True)
            self.account_label.set_text("Not signed in")
            return
        self.error_page.set_title("Proton Drive CLI error")
        self.error_page.set_description(str(exc)[:500])
        self.stack.set_visible_child_name("error")
        self._toast(str(exc)[:180])

    def _toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    def _on_version(self, text: str) -> None:
        line = text.splitlines()[0] if text else "Official CLI"
        self.version_label.set_text(line)

    def _on_version_error(self, exc: BaseException) -> None:
        self.version_label.set_text(str(exc)[:120])

    def _on_section(self, _list, row) -> None:
        path = getattr(row, "path", "/my-files")
        labels = {p: n for n, p, _ in SECTIONS}
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
        self._set_busy(True, f"Reading {path}")
        self.path_title.set_title(self.crumbs[-1][0])
        self.path_title.set_subtitle(path)
        self.back_btn.set_sensitive(len(self.crumbs) > 1)
        in_trash = self.section == "/trash"
        if self.empty_trash_btn is not None:
            self.empty_trash_btn.set_visible(in_trash)
        if self.trash_btn is not None:
            self.trash_btn.set_tooltip_text("Restore" if in_trash else "Move to trash")
        if self.section == "/photos":
            cache = self._timeline_cache
            self._bg(lambda: self._load_photos(path, cache), self._on_photos)
            return
        self._bg(lambda: self._load_files(path), self._on_list)

    def _load_photos(self, path: str, cache: list | None):
        timeline = cache if cache is not None else self.cli.photo_timeline()
        if path == "/photos":
            return {"kind": "root", "timeline": timeline, "albums": self.cli.album_list()}
        if path.startswith("/albums/"):
            return {"kind": "album", "timeline": timeline, "photos": self.cli.album_photos(path)}
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
                name = node_name(album) if album.get("name") else str(album.get("path") or album.get("uid") or "Album")
                album_path = str(album.get("path") or join_path("/albums", name))
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
            for node in payload.get("photos") or []:
                uid = str(node.get("uid") or node.get("nodeUid") or "")
                photo_path = f"/photos/{uid}" if uid else self.current_path
                if node.get("type") != "photo":
                    node = dict(node)
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
        self.account_label.set_text(self.email or "Signed in")
        count = self.store.get_n_items()
        if count == 0:
            self.empty.set_title("No photos")
            self.empty.set_description("Photos come from the official CLI timeline for this Proton account.")
            self.stack.set_visible_child_name("empty")
            self.status.set_text("0 items")
            return
        self.empty.set_title("This folder is empty")
        self.empty.set_description("Upload files with the official Proton Drive CLI session on this machine.")
        self.stack.set_visible_child_name("list")
        extra = f"{len(timeline)} photos" if kind == "root" else (self.email or "Proton Drive")
        self.status.set_text(f"{count} items · {extra}")

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
        self.account_label.set_text(self.email or "Signed in")
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
                self.empty.set_title("Nothing shared with you")
                self.empty.set_description("Pending invitations from proton-drive invitation list appear here. Share your own files from My files.")
            elif self.section == "/trash":
                self.empty.set_title("Trash is empty")
                self.empty.set_description("Trashed files appear here. Empty trash permanently deletes everything in /trash.")
            else:
                self.empty.set_title("This folder is empty")
                self.empty.set_description("Upload files with the official Proton Drive CLI session on this machine.")
            self.stack.set_visible_child_name("empty")
            self.status.set_text("0 items")
            return
        self.empty.set_title("This folder is empty")
        self.empty.set_description("Upload files with the official Proton Drive CLI session on this machine.")
        self.stack.set_visible_child_name("list")
        pending = f" · {len(invitations)} invitation(s)" if invitations else ""
        self.status.set_text(f"{count} items · {self.email or 'Proton Drive'}{pending}")

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
            self._toast("Select an item first")
            return
        if self._item_popover is not None:
            self._item_popover.popdown()
            self._item_popover.unparent()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        if self.section == "/trash":
            actions = [("Restore", self._trash), ("Empty trash", self._empty_trash)]
        else:
            actions = [("Rename", self._rename), ("Copy", self._copy), ("Move", self._move)]
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
        self._toast("Complete Proton sign-in in the browser, then this window will refresh.")
        self._bg(self.cli.login, lambda *_: self.reload(), self._fail)

    def _new_folder(self, *_args) -> None:
        if self.section == "/photos":
            self._toast("Create folders in My files. Photos are grouped by capture date.")
            return
        dialog = Adw.MessageDialog(transient_for=self, heading="New folder", body="Folder name")
        entry = Gtk.Entry(placeholder_text="Name")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
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

    def _upload(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Upload to Proton Drive")
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
        self._set_busy(True, f"Uploading {len(paths)} item(s)")
        if self.section == "/photos":
            self._bg(lambda: self.cli.photo_upload(paths), lambda *_: (self._toast("Upload finished"), self.reload()))
            return
        self._bg(lambda: self.cli.upload(paths, parent), lambda *_: (self._toast("Upload finished"), self.reload()))

    def _download(self, *_args) -> None:
        item = self._selected()
        if item is None:
            self._toast("Select a file or folder first")
            return
        self._download_item(item)

    def _download_item(self, item: DriveItem) -> None:
        if item.kind in ("day", "album"):
            self._toast("Open a day or album, then select a photo")
            return
        if item.kind == "invitation":
            InvitationDialog(self, item).present()
            return
        dest = str(download_folder())
        self._set_busy(True, f"Downloading {item.name}")

        def work():
            if item.kind == "photo" or self.section == "/photos":
                self.cli.photo_download(item.path, dest)
            else:
                self.cli.download(item.path, dest)
            return dest

        def done(folder: str) -> None:
            self._toast(f"Saved to {folder}")
            self.reload()
            subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self._bg(work, done)

    def _trash(self, *_args) -> None:
        item = self._selected()
        if item is None:
            self._toast("Select an item first")
            return
        if item.kind == "invitation":
            InvitationDialog(self, item).present()
            return
        if self.section == "/trash":
            self._bg(lambda: self.cli.restore(item.path), lambda *_: (self._toast("Restored"), self.reload()))
            return
        self._bg(lambda: self.cli.trash(item.path), lambda *_: (self._toast("Moved to trash"), self.reload()))

    def _mutate_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._toast(str(exc)[:180])

    def _file_op_item(self) -> DriveItem | None:
        item = self._selected()
        if item is None:
            self._toast("Select a file or folder first")
            return None
        if item.kind in ("invitation", "day", "album"):
            self._toast("Select a file or folder first")
            return None
        if self.section == "/trash" or item.path.startswith("/trash"):
            self._toast("Restore the item from Trash first")
            return None
        if item.path in _UNSHAREABLE_ROOTS:
            self._toast("Select a file or folder first")
            return None
        return item

    def _default_dest(self) -> str:
        if self.section in ("/trash", "/photos") or self.current_path in _UNSHAREABLE_ROOTS:
            return "/my-files"
        if self.current_path.startswith("/photos"):
            return "/my-files"
        return self.current_path

    def _rename(self, *_args) -> None:
        item = self._file_op_item()
        if item is None:
            return
        dialog = Adw.MessageDialog(transient_for=self, heading="Rename", body=item.path)
        entry = Gtk.Entry()
        entry.set_text(item.name)
        entry.set_placeholder_text("New name")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_default_response("rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_rename, item, entry)
        dialog.present()

    def _on_rename(self, _dialog, response: str, item: DriveItem, entry: Gtk.Entry) -> None:
        if response != "rename":
            return
        name = entry.get_text().strip()
        if not name:
            self._toast("Enter a name")
            return
        if name == item.name:
            return
        path = item.path
        self._bg(lambda: self.cli.rename(path, name), lambda *_: (self._toast(f"Renamed to {name}"), self.reload()), self._mutate_error)

    def _copy(self, *_args) -> None:
        item = self._file_op_item()
        if item is None:
            return
        DestinationDialog(self, item, "copy").present(self)

    def _move(self, *_args) -> None:
        item = self._file_op_item()
        if item is None:
            return
        DestinationDialog(self, item, "move").present(self)

    def _empty_trash(self, *_args) -> None:
        if self.section != "/trash":
            self._toast("Open Trash to empty it")
            return
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Empty trash?",
            body="Permanently deletes every item in Trash. Photos trash is not affected. This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("empty", "Empty trash")
        dialog.set_default_response("cancel")
        dialog.set_response_appearance("empty", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_empty_trash)
        dialog.present()

    def _on_empty_trash(self, _dialog, response: str) -> None:
        if response != "empty":
            return
        self._set_busy(True, "Emptying trash")
        self._bg(self.cli.empty_trash, lambda *_: (self._toast("Trash emptied"), self.reload()), self._mutate_error)

    def _share(self, *_args) -> None:
        item = self._selected()
        if item is not None and item.kind == "invitation":
            InvitationDialog(self, item).present()
            return
        if item is None:
            if self.current_path in _UNSHAREABLE_ROOTS or _photos_day(self.current_path):
                if self.section == "/shared-with-me":
                    self._toast("Select a shared item, or open Shared with me to see pending invitations")
                else:
                    self._toast("Select a file or folder to share")
                return
            item = DriveItem({"type": "folder", "name": self.crumbs[-1][0]}, self.current_path)
        if item.kind in ("day", "album"):
            self._toast("Open a day or album, then share a photo")
            return
        if item.path in _UNSHAREABLE_ROOTS or item.path.startswith("/trash"):
            self._toast("Select a file or folder inside My files to share")
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
        verb = "Copy" if action == "copy" else "Move"
        self.set_title(f"{verb} {item.name}")
        self.set_content_width(480)
        self.set_content_height(520)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.path_title = Adw.WindowTitle(title=verb, subtitle=self.dest_path)
        header.set_title_widget(self.path_title)
        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back")
        self.back_btn.connect("clicked", lambda *_: self._go_up())
        header.pack_start(self.back_btn)
        toolbar.add_top_bar(header)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=16, margin_end=16, margin_top=8, margin_bottom=16)
        page.append(Gtk.Label(label=f"{verb} \"{item.name}\" into a folder. Click a folder to open it.", xalign=0, wrap=True, css_classes=["dim-label"]))
        roots = Gtk.DropDown.new_from_strings(["My files", "Shared with me"])
        roots.set_selected(0)
        roots.connect("notify::selected", self._on_root)
        page.append(roots)
        self.root_drop = roots
        if action == "copy":
            self.name_entry = Gtk.Entry(text=item.name, placeholder_text="Name of the copy")
            page.append(self.name_entry)
        else:
            self.name_entry = None
        scrolled = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.folders = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["boxed-list"])
        self.folders.connect("row-activated", self._on_folder)
        scrolled.set_child(self.folders)
        page.append(scrolled)
        self.empty = Gtk.Label(label="No folders here. Use the button to copy into this location.", xalign=0, wrap=True, css_classes=["dim-label"])
        page.append(self.empty)
        confirm = Gtk.Button(label=f"{verb} here", css_classes=["suggested-action"], halign=Gtk.Align.START)
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
            self.window._toast("Choose a different folder")
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
            verb = "Copied" if action == "copy" else "Moved"
            window._toast(f"{verb} to {dest}")
            window.reload()

        window._set_busy(True, f"{'Copying' if action == 'copy' else 'Moving'} {self.item.name}")
        window._bg(work, done, window._mutate_error)


class InvitationDialog(Adw.MessageDialog):
    def __init__(self, window: DriveWindow, item: DriveItem) -> None:
        uid = invitation_uid(item.node)
        inviter = added_by_email(item.node) or "Someone"
        role = member_role(item.node)
        super().__init__(
            transient_for=window,
            heading=item.name,
            body=f"{inviter} invited you as {role}. Accept or reject uses the official CLI invitation UID.",
        )
        self.window = window
        self.uid = uid
        self.add_response("cancel", "Cancel")
        self.add_response("reject", "Reject")
        self.add_response("accept", "Accept")
        self.set_response_appearance("reject", Adw.ResponseAppearance.DESTRUCTIVE)
        self.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self._on_response)

    def _on_response(self, _dialog, response: str) -> None:
        if response not in ("accept", "reject") or not self.uid:
            if response in ("accept", "reject") and not self.uid:
                self.window._toast("Invitation has no UID from proton-drive invitation list")
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
            self.window._toast("Invitation accepted" if action == "accept" else "Invitation rejected")
            self.window.reload()

        self.window._bg(work, done, self.window._share_error)


class ShareDialog(Adw.Dialog):
    def __init__(self, window: DriveWindow, item: DriveItem) -> None:
        super().__init__()
        self.window = window
        self.item = item
        self.status: dict = {}
        self.set_title(f"Share {item.name}")
        self.set_content_width(520)
        self.set_content_height(620)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Share", subtitle=item.path))
        toolbar.add_top_bar(header)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_start=16, margin_end=16, margin_top=8, margin_bottom=16)
        scrolled = Gtk.ScrolledWindow(hexpand=True, vexpand=True, propagate_natural_height=True)
        scrolled.set_child(page)
        toolbar.set_content(scrolled)
        self.set_child(toolbar)

        invite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        invite.append(Gtk.Label(label="Invite people", xalign=0, css_classes=["heading"]))
        self.email = Gtk.Entry(placeholder_text="Email address")
        self.email.connect("activate", self._invite)
        invite.append(self.email)
        self.role = Gtk.DropDown.new_from_strings(list(_INVITE_ROLES))
        self.role.set_selected(0)
        invite.append(self.role)
        self.message = Gtk.Entry(placeholder_text="Optional message in the invitation email")
        invite.append(self.message)
        self.include_name = Gtk.CheckButton(label="Include the file name in the email (clear text)")
        invite.append(self.include_name)
        send = Gtk.Button(label="Send invitation", css_classes=["suggested-action"], halign=Gtk.Align.START)
        send.connect("clicked", self._invite)
        invite.append(send)
        page.append(invite)

        people = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        people.append(Gtk.Label(label="People with access", xalign=0, css_classes=["heading"]))
        self.people = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        people.append(self.people)
        self.people_empty = Gtk.Label(label="Not shared yet", xalign=0, css_classes=["dim-label"])
        people.append(self.people_empty)
        page.append(people)

        link = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        link.append(Gtk.Label(label="Public link", xalign=0, css_classes=["heading"]))
        self.link_label = Gtk.Label(label="No public link", xalign=0, wrap=True, selectable=True)
        link.append(self.link_label)
        self.link_role = Gtk.DropDown.new_from_strings(list(_LINK_ROLES))
        self.link_role.set_selected(0)
        link.append(self.link_role)
        self.link_password = Gtk.PasswordEntry(placeholder_text="Optional link password", show_peek_icon=True)
        link.append(self.link_password)
        self.link_expiration = Gtk.Entry(placeholder_text="Optional expiration (YYYY-MM-DD)")
        link.append(self.link_expiration)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.link_create = Gtk.Button(label="Create or update link")
        self.link_create.connect("clicked", self._set_url)
        self.link_copy = Gtk.Button(label="Copy link")
        self.link_copy.connect("clicked", self._copy_url)
        self.link_remove = Gtk.Button(label="Remove link", css_classes=["destructive-action"])
        self.link_remove.connect("clicked", self._remove_url)
        buttons.append(self.link_create)
        buttons.append(self.link_copy)
        buttons.append(self.link_remove)
        link.append(buttons)
        page.append(link)

        danger = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if window.section == "/shared-with-me":
            leave = Gtk.Button(label="Leave share", css_classes=["destructive-action"])
            leave.connect("clicked", self._leave)
            danger.append(leave)
        else:
            stop = Gtk.Button(label="Stop sharing", css_classes=["destructive-action"])
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
                rows.append((item, "Pending invitation"))
        for item in self.status.get("nonProtonInvitations") or []:
            if isinstance(item, dict):
                state = str(item.get("state") or "pending")
                rows.append((item, f"External · {state}"))
        for item in self.status.get("members") or []:
            if isinstance(item, dict):
                rows.append((item, "Member"))
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
            label = Gtk.Label(label=f"{email or 'Unknown'} · {role} · {kind}", xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
            row.append(label)
            if email and self.window.section != "/shared-with-me":
                remove = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER)
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
            self.link_label.set_text(f"{url}\nRole: {role}")
            self.link_copy.set_sensitive(True)
            self.link_remove.set_sensitive(True)
        else:
            self.link_label.set_text("No public link")
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
            self.window._toast("Enter an email to invite")
            return
        if any("@" not in email for email in emails):
            self.window._toast("Enter a valid email address")
            return
        path = self.item.path
        role = self._invite_role()
        message = self.message.get_text().strip() or None
        include = bool(self.include_name.get_active())

        def work():
            return self.window.cli.sharing_invite(path, emails, role=role, message=message, include_node_name=include)

        def done(result) -> None:
            self.email.set_text("")
            self.window._toast("Invitation sent")
            self._on_status(result)

        self.window._bg(work, done, self.window._share_error)

    def _remove_email(self, _button, email: str) -> None:
        path = self.item.path

        def work():
            self.window.cli.sharing_remove(path, emails=[email])
            return self.window.cli.sharing_status(path)

        def done(status) -> None:
            self.window._toast(f"Removed {email}")
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
            self.window._toast("Public link updated")
            self._on_status(result)

        self.window._bg(work, done, self.window._share_error)

    def _copy_url(self, *_args) -> None:
        access = self.status.get("urlAccess")
        url = str(access.get("url") or "") if isinstance(access, dict) else ""
        if not url:
            self.window._toast("No public link")
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        display.get_clipboard().set(url)
        self.window._toast("Link copied")

    def _remove_url(self, *_args) -> None:
        path = self.item.path

        def work():
            self.window.cli.sharing_remove_url(path)
            return self.window.cli.sharing_status(path)

        def done(status) -> None:
            self.window._toast("Public link removed")
            self._on_status(status)

        self.window._bg(work, done, self.window._share_error)

    def _leave(self, *_args) -> None:
        path = self.item.path

        def work():
            self.window.cli.sharing_leave(path)
            return True

        def done(_ok) -> None:
            self.window._toast("Left share")
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
            self.window._toast("Stopped sharing")
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
        settings.append("Settings", "app.preferences")
        settings.append("Open Drive in browser", "app.open-browser")
        settings.append("Open sync folder", "app.open-sync")
        menu.append_section(None, settings)
        help_section = Gio.Menu()
        help_section.append("Proton Drive Help", "app.help")
        help_section.append("Drive CLI Help", "app.cli-help")
        help_section.append("Open CLI logs", "app.logs")
        menu.append_section(None, help_section)
        about = Gio.Menu()
        about.append("About Proton Drive Linux", "app.about")
        menu.append_section(None, about)
        quit_section = Gio.Menu()
        quit_section.append("Quit", "app.quit")
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
                title="Proton Drive",
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
        if self._sync_proc is not None and self._sync_proc.poll() is None:
            self._sync_proc.terminate()
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
            comments="Unofficial GTK4 GUI for Proton’s official Drive CLI. Not affiliated with Proton AG.",
            website=WEBSITE_URL,
            issue_url=ISSUE_URL,
            copyright="GUI © 2026 VoxHash Technologies. Proton Drive mark © Proton AG.",
            license_type=Gtk.License.MIT_X11,
        )
        about.add_link("Proton Drive Help", HELP_URL)
        about.add_link("Terms of Service", TERMS_URL)
        about.add_link("Privacy Policy", PRIVACY_URL)
        if self._window is not None:
            try:
                about.set_debug_info(self._window.cli.version())
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
        super().__init__(title="Settings")
        self.window = window
        self.cfg = load_config()
        self.set_content_width(560)

        account = Adw.PreferencesPage(title="Account", icon_name="avatar-default-symbolic")
        app_page = Adw.PreferencesPage(title="Application", icon_name="applications-system-symbolic")
        self.add(account)
        self.add(app_page)

        who = Adw.PreferencesGroup(
            title="Proton account",
            description="Taken from the official CLI session in the system keyring.",
        )
        self.email_row = Adw.ActionRow(title="Signed in as", subtitle=window.email or "Reading live session…")
        account_btn = Gtk.Button(label="Proton Account", valign=Gtk.Align.CENTER)
        account_btn.connect("clicked", lambda *_: window.get_application()._open_url(ACCOUNT_URL))
        self.email_row.add_suffix(account_btn)
        who.add(self.email_row)
        self.cli_version_row = Adw.ActionRow(title="CLI", subtitle="Reading proton-drive version…")
        who.add(self.cli_version_row)
        signout = Adw.ButtonRow(title="Sign out")
        signout.add_css_class("destructive-action")
        signout.connect("activated", self._sign_out)
        who.add(signout)
        account.add(who)

        cli_group = Adw.PreferencesGroup(
            title="Official CLI",
            description="This GUI only runs the proton-drive binary already installed on this machine.",
        )
        self.cli_row = Adw.ActionRow(title="CLI path", subtitle=self._cli_path_text())
        choose_cli = Gtk.Button(label="Choose", valign=Gtk.Align.CENTER)
        choose_cli.connect("clicked", self._choose_cli)
        self.cli_row.add_suffix(choose_cli)
        cli_group.add(self.cli_row)
        account.add(cli_group)

        appearance = Adw.PreferencesGroup(title="Appearance")
        themes = Gtk.StringList.new(["Dark", "Light", "System"])
        self.theme_row = Adw.ComboRow(title="Theme", model=themes)
        current = str(self.cfg.get("theme") or "dark").lower()
        self.theme_row.set_selected({"dark": 0, "light": 1, "system": 2}.get(current, 0))
        self.theme_row.connect("notify::selected", self._on_theme)
        appearance.add(self.theme_row)
        app_page.add(appearance)

        folders = Adw.PreferencesGroup(
            title="Downloads",
            description="One-off downloads from the toolbar. This is not the always-on My files folder.",
        )
        self.download_row = Adw.ActionRow(title="Download folder", subtitle=str(download_folder()))
        choose_dl = Gtk.Button(label="Choose", valign=Gtk.Align.CENTER)
        choose_dl.connect("clicked", self._choose_download)
        self.download_row.add_suffix(choose_dl)
        folders.add(self.download_row)
        app_page.add(folders)

        sync = Adw.PreferencesGroup(
            title="My files folder",
            description="Official CLI 0.8.0 cannot FUSE-mount Drive. When enabled, a separate niced process skip/merge-copies /my-files into this local folder and uploads new local children. Existing files are never replaced.",
        )
        self.sync_switch = Adw.SwitchRow(title="Keep a local My files folder")
        self.sync_switch.set_active(bool(self.cfg.get("sync_enabled")))
        self.sync_switch.connect("notify::active", self._on_sync_enabled)
        sync.add(self.sync_switch)
        self.sync_folder_row = Adw.ActionRow(title="Folder", subtitle=str(self.cfg.get("sync_folder") or configured_sync_folder()))
        choose_sync = Gtk.Button(label="Choose", valign=Gtk.Align.CENTER)
        choose_sync.connect("clicked", self._choose_sync)
        self.sync_folder_row.add_suffix(choose_sync)
        open_sync = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
        open_sync.connect("clicked", lambda *_: window.get_application()._on_open_sync())
        self.sync_folder_row.add_suffix(open_sync)
        sync.add(self.sync_folder_row)
        self.sync_status_row = Adw.ActionRow(title="Status", subtitle=format_status_line())
        sync_now = Gtk.Button(label="Sync now", valign=Gtk.Align.CENTER)
        sync_now.connect("clicked", self._sync_now)
        self.sync_status_row.add_suffix(sync_now)
        sync.add(self.sync_status_row)
        app_page.add(sync)

        startup = Adw.PreferencesGroup(
            title="Startup",
            description="Same idea as the Windows Drive setting, using XDG autostart.",
        )
        self.autostart_row = Adw.SwitchRow(title="Start with this session")
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
        return {"email": email, "version": cli.version(), "path": find_binary()}

    def _on_live(self, payload: dict) -> None:
        email = payload.get("email") or ""
        if email:
            self.window.email = email
            self.window.account_label.set_text(email)
        self.email_row.set_subtitle(email or "Not signed in")
        version = str(payload.get("version") or "").splitlines()[0]
        self.cli_version_row.set_subtitle(version)
        self.cli_row.set_subtitle(str(payload.get("path") or self._cli_path_text()))

    def _on_live_error(self, exc: BaseException) -> None:
        if isinstance(exc, NotLoggedIn):
            self.email_row.set_subtitle("Not signed in")
            return
        self.cli_version_row.set_subtitle(str(exc)[:160])

    def _persist(self, **updates) -> None:
        self.cfg.update(updates)
        save_config(self.cfg)

    def _on_theme(self, row, _pspec) -> None:
        name = ["dark", "light", "system"][int(row.get_selected())]
        self._persist(theme=name)
        apply_theme(name)

    def _on_autostart(self, row, _pspec) -> None:
        enabled = bool(row.get_active())
        _set_autostart(enabled)
        self._persist(autostart=enabled)

    def _choose_download(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Download folder")
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
        dialog = Gtk.FileDialog(title="My files folder")
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

    def _on_sync_enabled(self, row, _pspec) -> None:
        enabled = bool(row.get_active())
        if enabled:
            Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(parents=True, exist_ok=True)
        self._persist(sync_enabled=enabled)
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application._refresh_sync_label()

    def _sync_now(self, *_args) -> None:
        Path(str(self.cfg.get("sync_folder") or configured_sync_folder())).expanduser().mkdir(parents=True, exist_ok=True)
        self._persist(sync_enabled=True)
        self.sync_switch.set_active(True)
        application = self.window.get_application()
        if isinstance(application, DriveApp):
            application.start_sync_now()
            self.sync_status_row.set_subtitle(format_status_line())

    def _choose_cli(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Official proton-drive binary")
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
        self.window._bg(self.window.cli.version, lambda text: self.cli_version_row.set_subtitle(text.splitlines()[0] if text else path))

    def _sign_out(self, *_args) -> None:
        def work():
            self.window.cli.logout()
            return True

        def done(_ok) -> None:
            self.window.email = ""
            self.email_row.set_subtitle("Not signed in")
            self.window.account_label.set_text("Not signed in")
            self.window.reload()
            self.close()

        self.window._bg(work, done)


def main() -> int:
    Adw.init()
    os.environ.setdefault("ADW_DISABLE_PORTAL", "0")
    apply_theme()
    app = DriveApp()
    return app.run()
