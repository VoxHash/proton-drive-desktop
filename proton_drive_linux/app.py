"""GTK4 / libadwaita desktop UI for the official Proton Drive CLI."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from .cli import (
    CliError,
    NotLoggedIn,
    ProtonDriveCli,
    account_email,
    format_size,
    join_path,
    node_name,
    node_size,
)
from .tray import StatusNotifierTray

APP_ID = "io.github.voxhash.ProtonDriveLinux"
SECTIONS = (
    ("My files", "/my-files", "folder-documents-symbolic"),
    ("Photos", "/photos", "folder-pictures-symbolic"),
    ("Shared with me", "/shared-with-me", "system-users-symbolic"),
    ("Trash", "/trash", "user-trash-symbolic"),
)


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
            margin_bottom=16,
            css_classes=["dim-label"],
        )
        side_box.append(self.version_label)
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

        for icon, tip, handler in (
            ("folder-new-symbolic", "New folder", self._new_folder),
            ("document-save-symbolic", "Upload", self._upload),
            ("folder-download-symbolic", "Download", self._download),
            ("document-open-symbolic", "Open", self._open_selected),
            ("user-trash-symbolic", "Move to trash", self._trash),
            ("view-refresh-symbolic", "Refresh", lambda *_: self.reload()),
        ):
            btn = Gtk.Button(icon_name=icon, tooltip_text=tip)
            btn.connect("clicked", handler)
            header.pack_end(btn)

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
        if self.section == "/photos":
            cache = self._timeline_cache
            self._bg(lambda: self._load_photos(path, cache), self._on_photos)
            return
        self._bg(lambda: self.cli.list(path), self._on_list)

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

    def _on_list(self, nodes: list) -> None:
        self._set_busy(False)
        self.login_btn.set_visible(False)
        self.store.remove_all()
        email = account_email(nodes)
        if email:
            self.email = email
        self.account_label.set_text(self.email or "Signed in")
        folders = [n for n in nodes if n.get("type") == "folder"]
        files = [n for n in nodes if n.get("type") != "folder"]
        for node in folders + files:
            self.store.append(DriveItem(node, join_path(self.current_path, node_name(node))))
        count = self.store.get_n_items()
        if count == 0:
            self.stack.set_visible_child_name("empty")
            self.status.set_text("0 items")
            return
        self.stack.set_visible_child_name("list")
        self.status.set_text(f"{count} items · {self.email or 'Proton Drive'}")

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
        return False

    def _on_activate(self, _view, position: int) -> None:
        item = self.store.get_item(position)
        if not isinstance(item, DriveItem):
            return
        if item.kind in ("folder", "day", "album"):
            self.crumbs.append((item.name, item.path))
            self.current_path = item.path
            self.reload()
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
        dest = str(Path.home() / "Downloads")
        Path(dest).mkdir(parents=True, exist_ok=True)
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
        if self.section == "/trash":
            self._bg(lambda: self.cli.restore(item.path), lambda *_: (self._toast("Restored"), self.reload()))
            return
        self._bg(lambda: self.cli.trash(item.path), lambda *_: (self._toast("Moved to trash"), self.reload()))


class DriveApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._window: DriveWindow | None = None
        self._tray: StatusNotifierTray | None = None
        self._allow_quit = False
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app) -> None:
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
                icon_name="folder-remote",
                on_show=self.show_window,
                on_hide=self.hide_window,
                on_open_files=self.open_my_files,
                on_quit=self.quit_from_tray,
            )
            self._tray.start()
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
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        self.quit()


def main() -> int:
    Adw.init()
    os.environ.setdefault("ADW_DISABLE_PORTAL", "0")
    style = Adw.StyleManager.get_default()
    style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    app = DriveApp()
    return app.run()
