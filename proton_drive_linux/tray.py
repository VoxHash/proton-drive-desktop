"""StatusNotifierItem + DBusMenu tray for the GTK4 Proton Drive window (KDE/Ayatana)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib

SNI_INTERFACE = "org.kde.StatusNotifierItem"
SNI_PATH = "/StatusNotifierItem"
DBUSMENU_INTERFACE = "com.canonical.dbusmenu"
DBUSMENU_PATH = "/MenuBar"
SNW_BUS_NAME = "org.kde.StatusNotifierWatcher"
SNW_PATH = "/StatusNotifierWatcher"
SNW_INTERFACE = "org.kde.StatusNotifierWatcher"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <method name="ContextMenu">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Activate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Scroll">
      <arg type="i" name="delta" direction="in"/>
      <arg type="s" name="orientation" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg type="s" name="status"/>
    </signal>
    <signal name="NewMenu"/>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg type="i" name="id"/>
      <arg type="u" name="timestamp"/>
    </signal>
  </interface>
</node>
"""


def watcher_available(timeout_ms: int = 400) -> bool:
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        dbus = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            None,
        )
        has_owner = dbus.call_sync(
            "NameHasOwner",
            GLib.Variant("(s)", (SNW_BUS_NAME,)),
            Gio.DBusCallFlags.NONE,
            timeout_ms,
            None,
        ).unpack()[0]
        return bool(has_owner)
    except GLib.Error:
        return False


def _v_string(value: str) -> GLib.Variant:
    return GLib.Variant("s", value)


def _v_bool(value: bool) -> GLib.Variant:
    return GLib.Variant("b", value)


def _pack_props(props: dict) -> dict:
    packed = {}
    for key, value in props.items():
        if isinstance(value, bool):
            packed[key] = _v_bool(value)
        elif isinstance(value, int):
            packed[key] = GLib.Variant("i", value)
        else:
            packed[key] = _v_string(str(value))
    return packed


def _png_to_sni_pixmap(path: Path) -> list[tuple[int, int, bytes]]:
    if not path.is_file():
        return []
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
    pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
    width, height = pixbuf.get_width(), pixbuf.get_height()
    channels = pixbuf.get_n_channels()
    stride = pixbuf.get_rowstride()
    pixels = pixbuf.get_pixels()
    data = bytearray(width * height * 4)
    index = 0
    for row in range(height):
        for col in range(width):
            offset = row * stride + col * channels
            red, green, blue, alpha = pixels[offset : offset + 4]
            data[index] = alpha
            data[index + 1] = red
            data[index + 2] = green
            data[index + 3] = blue
            index += 4
    return [(width, height, bytes(data))]


class StatusNotifierTray:
    def __init__(
        self,
        *,
        app_id: str,
        title: str,
        icon_name: str,
        icon_theme_path: str = "",
        icon_png: str | Path | None = None,
        on_show: Callable[[], None],
        on_hide: Callable[[], None],
        on_open_files: Callable[[], None],
        on_open_sync: Callable[[], None],
        on_open_browser: Callable[[], None],
        on_settings: Callable[[], None],
        on_help: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self.app_id = app_id
        self.title = title
        self.icon_name = icon_name
        self.icon_theme_path = icon_theme_path
        self.on_show = on_show
        self.on_hide = on_hide
        self.on_open_files = on_open_files
        self.on_open_sync = on_open_sync
        self.on_open_browser = on_open_browser
        self.on_settings = on_settings
        self.on_help = on_help
        self.on_quit = on_quit
        self.available = False
        self.started = False
        self._owner_id = 0
        self._sni_reg = 0
        self._menu_reg = 0
        self._conn: Gio.DBusConnection | None = None
        self._bus_name = f"org.kde.StatusNotifierItem-{app_id}-{os.getpid()}"
        self._menu_revision = 1
        self._pixmaps = _png_to_sni_pixmap(Path(icon_png)) if icon_png else []
        self._menu_items = {
            1: ("Show window", self._run_show),
            2: ("Hide", self._run_hide),
            4: ("Open My files", self._run_open_files),
            5: ("Open always-on folder", self._run_open_sync),
            6: ("Open in browser", self._run_open_browser),
            8: ("Settings", self._run_settings),
            9: ("Help", self._run_help),
            11: ("Quit", self._run_quit),
        }
        self._separators = {3, 7, 10}

    def start(self) -> bool:
        if not watcher_available():
            return False
        self.started = True
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            self._bus_name,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            self._on_name_acquired,
            self._on_name_lost,
        )
        return True

    def stop(self) -> None:
        if self._conn is not None:
            if self._sni_reg:
                self._conn.unregister_object(self._sni_reg)
                self._sni_reg = 0
            if self._menu_reg:
                self._conn.unregister_object(self._menu_reg)
                self._menu_reg = 0
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        self.available = False
        self.started = False

    def _run_show(self) -> None:
        self.on_show()

    def _run_hide(self) -> None:
        self.on_hide()

    def _run_open_files(self) -> None:
        self.on_open_files()

    def _run_open_sync(self) -> None:
        self.on_open_sync()

    def _run_open_browser(self) -> None:
        self.on_open_browser()

    def _run_settings(self) -> None:
        self.on_settings()

    def _run_help(self) -> None:
        self.on_help()

    def _run_quit(self) -> None:
        self.on_quit()

    def _on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self._conn = connection
        sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
        menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML)
        self._sni_reg = connection.register_object(
            SNI_PATH,
            sni_info.interfaces[0],
            self._sni_method,
            self._sni_get_property,
            None,
        )
        self._menu_reg = connection.register_object(
            DBUSMENU_PATH,
            menu_info.interfaces[0],
            self._menu_method,
            self._menu_get_property,
            None,
        )

    def _on_name_acquired(self, connection: Gio.DBusConnection, name: str) -> None:
        try:
            proxy = Gio.DBusProxy.new_sync(
                connection,
                Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None,
                SNW_BUS_NAME,
                SNW_PATH,
                SNW_INTERFACE,
                None,
            )
            proxy.call_sync(
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (name,)),
                Gio.DBusCallFlags.NONE,
                3000,
                None,
            )
            self.available = True
        except GLib.Error:
            self.available = False

    def _on_name_lost(self, _connection: Gio.DBusConnection, _name: str) -> None:
        self.available = False

    def _sni_props(self) -> dict[str, GLib.Variant]:
        empty_pixmaps = GLib.Variant("a(iiay)", [])
        return {
            "Category": _v_string("ApplicationStatus"),
            "Id": _v_string(self.app_id),
            "Title": _v_string(self.title),
            "Status": _v_string("Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": _v_string(self.icon_name),
            "IconPixmap": GLib.Variant("a(iiay)", self._pixmaps) if self._pixmaps else empty_pixmaps,
            "OverlayIconName": _v_string(""),
            "OverlayIconPixmap": empty_pixmaps,
            "AttentionIconName": _v_string(""),
            "AttentionIconPixmap": empty_pixmaps,
            "AttentionMovieName": _v_string(""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (self.icon_name, [], self.title, "Proton Drive")),
            "ItemIsMenu": _v_bool(False),
            "Menu": GLib.Variant("o", DBUSMENU_PATH),
            "IconThemePath": _v_string(self.icon_theme_path),
        }

    def _sni_get_property(self, *_args) -> GLib.Variant | None:
        name = _args[4] if len(_args) >= 5 else _args[-1]
        return self._sni_props().get(str(name))

    def _sni_method(self, _connection, _sender, _path, _iface, method: str, _params, invocation) -> None:
        if method in {"Activate", "SecondaryActivate"}:
            GLib.idle_add(self._run_show)
        invocation.return_value(None)

    def _menu_get_property(self, *_args) -> GLib.Variant | None:
        name = _args[4] if len(_args) >= 5 else _args[-1]
        props = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": _v_string("ltr"),
            "Status": _v_string("normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return props.get(str(name))

    def _item_props(self, item_id: int) -> dict:
        if item_id == 0:
            return {"children-display": "submenu"}
        if item_id in self._separators:
            return {"type": "separator", "visible": True}
        label, _cb = self._menu_items[item_id]
        return {"label": label, "enabled": True, "visible": True, "type": "standard"}

    def _layout_tuple(self, item_id: int) -> tuple:
        child_ids: list[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] if item_id == 0 else []
        children = []
        for child_id in child_ids:
            children.append(GLib.Variant("(ia{sv}av)", self._layout_tuple(child_id)))
        return (item_id, _pack_props(self._item_props(item_id)), children)

    def _menu_method(self, _connection, _sender, _path, _iface, method: str, params, invocation) -> None:
        if method == "GetLayout":
            parent_id = int(params[0])
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self._menu_revision, self._layout_tuple(parent_id))))
            return
        if method == "GetGroupProperties":
            ids = list(params[0])
            rows = []
            for item_id in ids:
                if item_id == 0 or item_id in self._menu_items or item_id in self._separators:
                    rows.append((int(item_id), _pack_props(self._item_props(int(item_id)))))
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (rows,)))
            return
        if method == "GetProperty":
            item_id, name = int(params[0]), str(params[1])
            props = _pack_props(self._item_props(item_id))
            invocation.return_value(GLib.Variant("(v)", (props.get(name, _v_string("")),)))
            return
        if method == "Event":
            item_id, event_id = int(params[0]), str(params[1])
            if event_id == "clicked" and item_id in self._menu_items:
                GLib.idle_add(self._menu_items[item_id][1])
            invocation.return_value(None)
            return
        if method == "EventGroup":
            events = list(params[0])
            for event in events:
                item_id, event_id = int(event[0]), str(event[1])
                if event_id == "clicked" and item_id in self._menu_items:
                    GLib.idle_add(self._menu_items[item_id][1])
            invocation.return_value(GLib.Variant("(ai)", ([],)))
            return
        if method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
            return
        if method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
            return
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
