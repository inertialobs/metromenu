"""The Windows 10 style start menu window."""

from __future__ import annotations

import getpass
import os
import pwd
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from . import actions as actions_mod  # noqa: E402
from . import apps as apps_mod  # noqa: E402
from . import config as config_mod  # noqa: E402
from . import desktop as desktop_mod  # noqa: E402
from . import icons  # noqa: E402
from . import timing  # noqa: E402
from .tiles import TileWidget, build_group_grid  # noqa: E402

POWER_ACTIONS = [
    ("锁定", "LOCK"),
    ("注销", "LOGOUT"),
    ("切换用户", "SWITCH_USER"),
    ("挂起", "SUSPEND"),
    ("重启", "RESTART"),
    ("关机", "SHUTDOWN"),
]

# Human readable names for the Metro palette (used by the tile colour menu).
COLOR_NAMES = {
    "#0078d7": "蓝色",
    "#2d7d9a": "灰蓝",
    "#00aba9": "青色",
    "#2d89ef": "亮蓝",
    "#1e7145": "墨绿",
    "#da532c": "砖红",
    "#b91d47": "玫红",
    "#6a00ff": "紫色",
    "#d24726": "橙色",
    "#8c0095": "深紫",
    "#008a00": "绿色",
    "#0050ef": "宝蓝",
    "#a20025": "深红",
    "#647687": "石板灰",
}


def _run(argv: list[str]) -> None:
    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def _power_action(action: str) -> None:
    candidates: list[list[str]] = []
    if action == "LOCK":
        candidates = [
            ["lxqt-leave", "--lockscreen"],
            ["xflock4"],
            ["loginctl", "lock-session"],
        ]
    elif action == "LOGOUT":
        candidates = [
            ["lxqt-leave", "--logout"],
            ["xfce4-session-logout", "--logout"],
        ]
        session_id = os.environ.get("XDG_SESSION_ID")
        if session_id:
            candidates.append(["loginctl", "terminate-session", session_id])
    elif action == "SWITCH_USER":
        # lxqt-leave 1.4 has no switch-user flag; a display-manager helper or
        # the Xfce logout dialog are the alternatives.
        candidates = [
            ["dm-tool", "switch-to-greeter"],
            ["xfce4-session-logout", "--switch-user"],
        ]
    elif action == "SUSPEND":
        candidates = [["lxqt-leave", "--suspend"], ["systemctl", "suspend"]]
    elif action == "HIBERNATE":
        candidates = [["lxqt-leave", "--hibernate"], ["systemctl", "hibernate"]]
    elif action == "RESTART":
        candidates = [["lxqt-leave", "--reboot"], ["systemctl", "reboot"]]
    elif action == "SHUTDOWN":
        candidates = [["lxqt-leave", "--shutdown"], ["systemctl", "poweroff"]]

    command = desktop_mod.first_available(candidates)
    if command is not None:
        _run(command)


def _which(program: str) -> bool:
    import shutil

    return shutil.which(program) is not None


class StartMenuWindow(Gtk.Window):
    def __init__(self, application: Gtk.Application, registry: apps_mod.AppRegistry, config: dict):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.application = application
        self.registry = registry
        self.config = config
        self.all_apps_mode = False
        self.query = ""
        self._tile_widgets: list[TileWidget] = []

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)
        self.set_accept_focus(True)
        self.set_focus_on_map(True)
        self.set_position(Gtk.WindowPosition.NONE)
        self.set_default_size(config["width"], config["height"])

        # RGBA so the CSS border-radius is honoured by the compositor.
        # NB: do NOT set app_paintable - that would stop GTK from drawing the
        # window's own CSS background, leaving the menu see-through.
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.get_style_context().add_class("start-menu")
        self._apply_background()

        self._build_ui()

        self.connect("delete-event", self._on_delete)
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("key-press-event", self._on_key_press)
        self.connect("show", self._on_show)
        self.connect("map-event", lambda *_: timing.log("window mapped") or False)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        outer.set_size_request(self.config["width"], self.config["height"])
        self.add(outer)

        outer.pack_start(self._build_rail(), False, False, 0)
        outer.pack_start(self._build_left_pane(), False, False, 0)
        outer.pack_start(self._build_tiles_pane(), True, True, 0)

    def _apply_background(self) -> None:
        """Apply the configured background colour and opacity to the window."""
        rgba = Gdk.RGBA()
        if not rgba.parse(self.config.get("background", "#1b1b1b")):
            rgba.parse("#1b1b1b")
        try:
            rgba.alpha = max(0.0, min(1.0, float(self.config.get("opacity", 0.96))))
        except (TypeError, ValueError):
            rgba.alpha = 0.96
        provider = Gtk.CssProvider()
        provider.load_from_data(
            f".start-menu {{ background-color: {rgba.to_string()}; }}".encode("utf-8")
        )
        self.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_rail(self) -> Gtk.Widget:
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        rail.get_style_context().add_class("rail")
        rail.set_size_request(48, -1)

        self.menu_button = self._rail_button("view-list-symbolic", "所有应用")
        self.menu_button.connect("clicked", lambda _b: self._toggle_all_apps())
        rail.pack_start(self.menu_button, False, False, 0)

        spacer = Gtk.Box()
        rail.pack_start(spacer, True, True, 0)

        settings_button = self._rail_button("preferences-system-symbolic", "系统设置")
        settings_button.connect("clicked", lambda _b: self._open_system_settings())
        rail.pack_start(settings_button, False, False, 0)

        avatar = self._build_avatar_button()
        rail.pack_start(avatar, False, False, 0)

        power_button = self._rail_button("system-shutdown-symbolic", "电源")
        power_button.connect("clicked", self._show_power_menu)
        rail.pack_start(power_button, False, False, 0)
        return rail

    def _rail_button(self, icon_name: str, tooltip: str) -> Gtk.Button:
        button = Gtk.Button()
        button.get_style_context().add_class("rail-button")
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(tooltip)
        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        button.add(image)
        return button

    def _build_avatar_button(self) -> Gtk.Button:
        button = Gtk.Button()
        button.get_style_context().add_class("rail-button")
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(self._display_user())
        image = Gtk.Image()
        pixbuf = self._load_avatar(32)
        if pixbuf is not None:
            image.set_from_pixbuf(pixbuf)
        else:
            image.set_from_icon_name("avatar-default", Gtk.IconSize.BUTTON)
        button.add(image)
        button.connect("clicked", self._show_user_menu)
        return button

    def _build_left_pane(self) -> Gtk.Widget:
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        pane.get_style_context().add_class("left-pane")
        pane.set_size_request(self.config["left_width"], -1)

        self.search = Gtk.SearchEntry()
        self.search.get_style_context().add_class("search-entry")
        self.search.set_placeholder_text("搜索")
        self.search.connect("search-changed", self._on_search_changed)
        self.search.connect("activate", self._on_search_activate)
        self.search.connect("key-press-event", self._on_search_key_press)
        pane.pack_start(self.search, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.app_list = Gtk.ListBox()
        self.app_list.get_style_context().add_class("app-list")
        self.app_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.app_list.set_activate_on_single_click(True)
        self.app_list.connect("row-activated", self._on_row_activated)
        # Right-click is handled on the list itself: rows have no GdkWindow of
        # their own, so their own button-press handlers never fire.
        self.app_list.connect("button-press-event", self._on_list_button_press)
        scrolled.add(self.app_list)
        pane.pack_start(scrolled, True, True, 0)
        return pane

    def _build_tiles_pane(self) -> Gtk.Widget:
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        pane.get_style_context().add_class("tiles-pane")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.tiles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.tiles_box.set_margin_start(12)
        self.tiles_box.set_margin_end(12)
        self.tiles_box.set_margin_top(10)
        self.tiles_box.set_margin_bottom(10)
        scrolled.add(self.tiles_box)
        pane.pack_start(scrolled, True, True, 0)
        return pane

    # ------------------------------------------------------------------
    # data population
    # ------------------------------------------------------------------
    def _populate(self) -> None:
        self._refresh_app_list()
        self._refresh_tiles()
        timing.log("populated")

    def _hidden_ids(self) -> set[str]:
        return set(self.config.get("hidden", []))

    def _is_hidden(self, desktop_id: str) -> bool:
        return desktop_id in self._hidden_ids()

    def _visible_apps(self) -> list[apps_mod.DesktopApp]:
        hidden = self._hidden_ids()
        return [app for app in self.registry.apps if app.desktop_id not in hidden]

    def _default_pinned(self) -> list[str]:
        hidden = self._hidden_ids()
        pinned = [
            pid
            for pid in self.config.get("pinned", [])
            if self.registry.get(pid) and pid not in hidden
        ]
        if pinned:
            return pinned
        result = []
        for candidate in config_mod.DEFAULT_TILE_CANDIDATES:
            if self.registry.get(candidate) and candidate not in hidden:
                result.append(candidate)
            if len(result) >= 8:
                break
        if not result:
            result = [app.desktop_id for app in self._visible_apps()[:8]]
        return result

    def _clear_list(self) -> None:
        for child in list(self.app_list.get_children()):
            self.app_list.remove(child)

    def _refresh_app_list(self) -> None:
        self._clear_list()
        if self.query:
            hidden = self._hidden_ids()
            results = [
                app
                for app in self.registry.search(self.query, limit=200)
                if app.desktop_id not in hidden
            ]
            if not results:
                self.app_list.add(self._message_row("无匹配结果"))
            for app in results:
                self.app_list.add(self._app_row(app, show_comment=True))
            self.app_list.show_all()
            return

        if self.all_apps_mode:
            self.app_list.add(self._back_row())
            self.app_list.add(self._pane_title("所有应用"))
            current_letter = None
            for app in self._visible_apps():
                letter = self._letter_of(app.name)
                if letter != current_letter:
                    current_letter = letter
                    self.app_list.add(self._letter_row(letter))
                self.app_list.add(self._app_row(app, show_comment=False))
        else:
            self.app_list.add(self._pane_title("常用"))
            for desktop_id in self._default_pinned():
                app = self.registry.get(desktop_id)
                if app:
                    self.app_list.add(self._app_row(app, show_comment=False))
            self.app_list.add(self._all_apps_row())
        self.app_list.show_all()

    @staticmethod
    def _letter_of(name: str) -> str:
        if not name:
            return "#"
        char = name.lstrip()[0].upper()
        return char if char.isalpha() else "#"

    def _pane_title(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        label = Gtk.Label(label=text, xalign=0.0)
        label.get_style_context().add_class("pane-title")
        row.add(label)
        return row

    def _message_row(self, text: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        label = Gtk.Label(label=text, xalign=0.0)
        label.get_style_context().add_class("app-row-comment")
        label.set_margin_start(12)
        label.set_margin_top(10)
        row.add(label)
        return row

    def _letter_row(self, letter: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        label = Gtk.Label(label=letter, xalign=0.0)
        label.get_style_context().add_class("letter-header")
        row.add(label)
        return row

    def _all_apps_row(self) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("app-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        image = Gtk.Image.new_from_icon_name("view-list-symbolic", Gtk.IconSize.BUTTON)
        label = Gtk.Label(label="所有应用", xalign=0.0)
        label.get_style_context().add_class("all-apps-row")
        box.pack_start(image, False, False, 0)
        box.pack_start(label, True, True, 0)
        row.add(box)
        row.all_apps = True
        return row

    def _back_row(self) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("app-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        image = Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
        label = Gtk.Label(label="常用", xalign=0.0)
        label.get_style_context().add_class("all-apps-row")
        box.pack_start(image, False, False, 0)
        box.pack_start(label, True, True, 0)
        row.add(box)
        row.back = True
        return row

    def _app_row(self, app: apps_mod.DesktopApp, show_comment: bool) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("app-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        image = Gtk.Image()
        pixbuf = icons.load_icon(app.icon, 24)
        if pixbuf is not None:
            image.set_from_pixbuf(pixbuf)
        else:
            image.set_from_icon_name("application-x-executable", Gtk.IconSize.BUTTON)
        box.pack_start(image, False, False, 0)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        name = Gtk.Label(label=app.name, xalign=0.0)
        name.get_style_context().add_class("app-row-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        labels.pack_start(name, False, False, 0)
        if show_comment and app.comment:
            comment = Gtk.Label(label=app.comment, xalign=0.0)
            comment.get_style_context().add_class("app-row-comment")
            comment.set_ellipsize(Pango.EllipsizeMode.END)
            labels.pack_start(comment, False, False, 0)
        box.pack_start(labels, True, True, 0)
        row.add(box)

        row.app = app
        return row

    def _refresh_tiles(self) -> None:
        for widget in self._tile_widgets:
            widget.stop()
        self._tile_widgets = []
        for child in list(self.tiles_box.get_children()):
            self.tiles_box.remove(child)

        tiles = self.config.get("tiles", [])
        hidden = self._hidden_ids()

        def tile_app(tile: dict):
            if tile["id"].startswith("@"):
                return None
            app = self.registry.get(tile["id"])
            if app is None or app.desktop_id in hidden:
                return None
            return app

        # Drop tiles whose application is not installed or is hidden.
        tiles = [t for t in tiles if t["id"].startswith("@") or tile_app(t) is not None]

        if self.query:
            filtered = []
            for tile in tiles:
                app = tile_app(tile)
                if app is not None and app.matches(self.query):
                    filtered.append(tile)
            tiles = filtered

        groups = list(self.config.get("groups", []))
        grouped: dict[str, list[dict]] = {}
        order: list[str] = []
        for tile in tiles:
            group = tile.get("group", "") or ""
            if group not in grouped:
                grouped[group] = []
                order.append(group)
            grouped[group].append(tile)

        if not tiles:
            label = Gtk.Label(label="没有磁贴", xalign=0.0)
            label.get_style_context().add_class("tile-empty")
            self.tiles_box.pack_start(label, False, False, 0)
            self.tiles_box.show_all()
            return

        for group in order:
            header = self._group_header(group)
            self.tiles_box.pack_start(header, False, False, 0)

            widgets = []
            for tile in grouped[group]:
                app = None
                if not tile["id"].startswith("@"):
                    app = self.registry.get(tile["id"])
                widget = TileWidget(tile, app, self._on_tile_launch, self._on_tile_context)
                self._tile_widgets.append(widget)
                widgets.append(widget)

            grid = build_group_grid(widgets)
            wrapper = Gtk.Box()
            wrapper.pack_start(grid, False, False, 0)
            wrapper.set_margin_bottom(14)
            self.tiles_box.pack_start(wrapper, False, False, 0)

        self.tiles_box.show_all()

    def _group_header(self, group: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label(label=group, xalign=0.0)
        label.get_style_context().add_class("group-title")
        box.pack_start(label, False, False, 0)
        box.set_margin_bottom(4)
        return box

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _launch_app(self, app: apps_mod.DesktopApp, action=None) -> None:
        if apps_mod.launch(app, action):
            self.request_hide()

    def _on_row_activated(self, _listbox, row) -> None:
        if getattr(row, "back", False):
            self.all_apps_mode = False
            self.menu_button.set_tooltip_text("所有应用")
            self._refresh_app_list()
            return
        if getattr(row, "all_apps", False):
            self.all_apps_mode = True
            self.menu_button.set_tooltip_text("返回")
            self._refresh_app_list()
            return
        app = getattr(row, "app", None)
        if app is not None:
            self._launch_app(app)

    def _on_tile_launch(self, widget: TileWidget) -> None:
        if widget.kind == "recent":
            self.all_apps_mode = True
            self._refresh_app_list()
            return
        if widget.app is not None:
            self._launch_app(widget.app)

    def _toggle_all_apps(self) -> None:
        self.all_apps_mode = not self.all_apps_mode
        self.menu_button.set_tooltip_text("常用" if self.all_apps_mode else "所有应用")
        self._refresh_app_list()

    # -- search ---------------------------------------------------------
    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.query = entry.get_text().strip()
        self._refresh_app_list()
        self._refresh_tiles()

    def _on_search_activate(self, _entry) -> None:
        rows = [r for r in self.app_list.get_children() if getattr(r, "app", None)]
        if rows:
            self._launch_app(rows[0].app)

    def _on_search_key_press(self, _entry, event: Gdk.EventKey) -> bool:
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            return self._move_selection(1 if event.keyval == Gdk.KEY_Down else -1)
        if event.keyval == Gdk.KEY_Return:
            return False
        return False

    def _move_selection(self, delta: int) -> bool:
        rows = [
            row
            for row in self.app_list.get_children()
            if row.get_selectable() and row.get_activatable()
        ]
        if not rows:
            return False
        selected = self.app_list.get_selected_row()
        try:
            index = rows.index(selected) if selected in rows else -1
        except ValueError:
            index = -1
        index = max(0, min(len(rows) - 1, index + delta))
        self.app_list.select_row(rows[index])
        return True

    # -- context menus --------------------------------------------------
    def _on_list_button_press(self, _listbox, event: Gdk.EventButton) -> bool:
        if event.button != 3:
            return False
        row = self.app_list.get_row_at_y(int(event.y))
        app = getattr(row, "app", None) if row is not None else None
        if app is None:
            return False
        menu = self._build_app_menu(app)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    @staticmethod
    def _menu_item(label: str, callback=None, sensitive: bool = True) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label=label)
        if callback is not None:
            item.connect("activate", lambda _i: callback())
        item.set_sensitive(sensitive)
        return item

    def _build_app_menu(self, app, tile_widget: TileWidget | None = None) -> Gtk.Menu:
        menu = Gtk.Menu()

        if app is not None:
            menu.append(self._menu_item("打开", lambda: self._launch_app(app)))

        if tile_widget is not None:
            menu.append(self._size_menu(tile_widget))
            menu.append(self._color_menu(tile_widget))
            menu.append(self._group_menu(tile_widget))
            if tile_widget.is_live():
                menu.append(self._live_menu(tile_widget))
            menu.append(self._menu_item("置顶", lambda: self._move_tile_to_front(tile_widget)))

        if app is not None and app.actions:
            actions_item = Gtk.MenuItem(label="操作")
            submenu = Gtk.Menu()
            for action in app.actions:
                item = Gtk.MenuItem(label=action.name)
                item.connect("activate", lambda _i, a=action: self._launch_app(app, a))
                submenu.append(item)
            actions_item.set_submenu(submenu)
            menu.append(actions_item)

        menu.append(Gtk.SeparatorMenuItem())

        if tile_widget is not None:
            menu.append(self._menu_item("从“开始”屏幕取消固定", lambda: self._unpin_tile(tile_widget)))
        elif app is not None:
            if self._is_pinned(app.desktop_id):
                menu.append(self._menu_item("从“开始”屏幕取消固定", lambda: self._unpin_app(app)))
            else:
                menu.append(self._menu_item("固定到“开始”屏幕", lambda: self._pin_tile(app)))
            menu.append(self._menu_item("置顶", lambda: self._move_to_top(app)))

        if app is not None:
            menu.append(Gtk.SeparatorMenuItem())
            menu.append(self._menu_item("打开文件位置", lambda: actions_mod.reveal_file(app.path)))
            menu.append(self._menu_item("编辑菜单项", lambda: actions_mod.edit_file(app.path)))
            menu.append(self._menu_item("复制启动命令", lambda: self._copy_command(app)))
            menu.append(self._menu_item("添加到桌面", lambda: actions_mod.add_to_desktop(app.path)))
            menu.append(self._menu_item("添加到面板", lambda: self._add_to_panel(app)))

            menu.append(Gtk.SeparatorMenuItem())
            hidden = self._is_hidden(app.desktop_id)
            menu.append(
                self._menu_item(
                    "取消隐藏" if hidden else "隐藏此应用",
                    lambda: self._toggle_hidden(app),
                )
            )

        return menu

    def _size_menu(self, widget: TileWidget) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label="调整大小")
        submenu = Gtk.Menu()
        current = widget.tile.get("size", "medium")
        for size, label in (("small", "小"), ("medium", "中"), ("wide", "宽"), ("large", "大")):
            entry = Gtk.CheckMenuItem(label=label)
            entry.set_active(size == current)
            entry.connect("activate", lambda _i, s=size: self._resize_tile(widget, s))
            submenu.append(entry)
        item.set_submenu(submenu)
        return item

    @staticmethod
    def _color_swatch(color: str, size: int = 14) -> Gtk.Image:
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, size, size)
        rgba = Gdk.RGBA()
        if rgba.parse(color):
            pixel = (
                (int(rgba.red * 255) << 24)
                | (int(rgba.green * 255) << 16)
                | (int(rgba.blue * 255) << 8)
                | 0xFF
            )
            pixbuf.fill(pixel)
        return Gtk.Image.new_from_pixbuf(pixbuf)

    def _color_menu(self, widget: TileWidget) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label="更改颜色")
        submenu = Gtk.Menu()
        current = (widget.tile.get("color") or "").lower()
        for color in config_mod.PALETTE:
            name = COLOR_NAMES.get(color.lower(), color)
            entry = Gtk.MenuItem()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.pack_start(self._color_swatch(color), False, False, 0)
            label = Gtk.Label(label=name, xalign=0.0)
            if color.lower() == current:
                label.set_markup(f"<b>{name}</b>")
            box.pack_start(label, True, True, 0)
            entry.add(box)
            entry.connect("activate", lambda _i, c=color: self._recolor_tile(widget, c))
            submenu.append(entry)
        submenu.append(Gtk.SeparatorMenuItem())
        custom = Gtk.MenuItem(label="自定义颜色…")
        custom.connect("activate", lambda _i: self._choose_custom_color(widget))
        submenu.append(custom)
        item.set_submenu(submenu)
        return item

    def _choose_custom_color(self, widget: TileWidget) -> None:
        dialog = Gtk.ColorChooserDialog(title="选择磁贴颜色", transient_for=self, modal=True)
        tile = self._find_tile(widget)
        if tile and tile.get("color"):
            rgba = Gdk.RGBA()
            if rgba.parse(tile["color"]):
                dialog.set_rgba(rgba)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self._recolor_tile(widget, dialog.get_rgba().to_string())
        dialog.destroy()

    def _group_menu(self, widget: TileWidget) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label="移动到分组")
        submenu = Gtk.Menu()
        current = widget.tile.get("group", "")
        for group in self.config.get("groups", []):
            entry = Gtk.CheckMenuItem(label=group or "未分组")
            entry.set_active(group == current)
            entry.connect("activate", lambda _i, g=group: self._regroup_tile(widget, g))
            submenu.append(entry)
        item.set_submenu(submenu)
        return item

    def _live_menu(self, widget: TileWidget) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label="实时磁贴")
        submenu = Gtk.Menu()
        on = Gtk.CheckMenuItem(label="开启")
        off = Gtk.CheckMenuItem(label="关闭")
        on.set_active(widget.live_enabled)
        off.set_active(not widget.live_enabled)
        on.connect("activate", lambda _i: self._set_tile_live(widget, True))
        off.connect("activate", lambda _i: self._set_tile_live(widget, False))
        submenu.append(on)
        submenu.append(off)
        item.set_submenu(submenu)
        return item

    def _is_pinned(self, desktop_id: str) -> bool:
        return any(tile["id"] == desktop_id for tile in self.config.get("tiles", []))

    def _pin_tile(self, app: apps_mod.DesktopApp) -> None:
        tiles = self.config.setdefault("tiles", [])
        groups = self.config.setdefault("groups", [])
        group = groups[0] if groups else ""
        color = config_mod.PALETTE[len(tiles) % len(config_mod.PALETTE)]
        tiles.append({"id": app.desktop_id, "size": "medium", "group": group, "color": color})
        config_mod.save(self.config)
        self._refresh_tiles()
        self._refresh_app_list()

    def _unpin_app(self, app: apps_mod.DesktopApp) -> None:
        self.config["tiles"] = [
            tile for tile in self.config.get("tiles", []) if tile["id"] != app.desktop_id
        ]
        config_mod.save(self.config)
        self._refresh_tiles()
        self._refresh_app_list()

    def _copy_command(self, app: apps_mod.DesktopApp) -> None:
        actions_mod.copy_text(app.exec_)

    def _add_to_panel(self, app: apps_mod.DesktopApp) -> None:
        actions_mod.add_launcher_to_panel(app.path)

    def _toggle_hidden(self, app: apps_mod.DesktopApp) -> None:
        hidden = set(self.config.get("hidden", []))
        if app.desktop_id in hidden:
            hidden.discard(app.desktop_id)
        else:
            hidden.add(app.desktop_id)
        self.config["hidden"] = sorted(hidden)
        config_mod.save(self.config)
        self._refresh_app_list()
        self._refresh_tiles()

    def _unhide_all(self) -> None:
        if not self.config.get("hidden"):
            return
        self.config["hidden"] = []
        config_mod.save(self.config)
        self._refresh_app_list()
        self._refresh_tiles()

    def _move_to_top(self, app: apps_mod.DesktopApp) -> None:
        pinned = list(self.config.get("pinned") or self._default_pinned())
        if app.desktop_id in pinned:
            pinned.remove(app.desktop_id)
        pinned.insert(0, app.desktop_id)
        self.config["pinned"] = pinned
        config_mod.save(self.config)
        self._refresh_app_list()

    def _move_tile_to_front(self, widget: TileWidget) -> None:
        tiles = self.config.get("tiles", [])
        tile = self._find_tile(widget)
        if tile is None:
            return
        group = tile.get("group", "")
        others = [t for t in tiles if t is not tile]
        index = next((i for i, t in enumerate(others) if t.get("group", "") == group), len(others))
        others.insert(index, tile)
        self.config["tiles"] = others
        config_mod.save(self.config)
        self._refresh_tiles()

    def _set_tile_live(self, widget: TileWidget, enabled: bool) -> None:
        tile = self._find_tile(widget)
        if tile is not None:
            tile["live"] = enabled
            config_mod.save(self.config)
            self._refresh_tiles()

    def _on_tile_context(self, widget: TileWidget, event: Gdk.EventButton) -> None:
        menu = self._build_app_menu(widget.app, widget)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _find_tile(self, widget: TileWidget) -> dict | None:
        for tile in self.config.get("tiles", []):
            if tile["id"] == widget.tile["id"]:
                return tile
        return None

    def _resize_tile(self, widget: TileWidget, size: str) -> None:
        tile = self._find_tile(widget)
        if tile is not None:
            tile["size"] = size
            config_mod.save(self.config)
            self._refresh_tiles()

    def _recolor_tile(self, widget: TileWidget, color: str) -> None:
        tile = self._find_tile(widget)
        if tile is not None:
            tile["color"] = color
            config_mod.save(self.config)
            self._refresh_tiles()

    def _regroup_tile(self, widget: TileWidget, group: str) -> None:
        tile = self._find_tile(widget)
        if tile is not None:
            tile["group"] = group
            config_mod.save(self.config)
            self._refresh_tiles()

    def _unpin_tile(self, widget: TileWidget) -> None:
        self.config["tiles"] = [
            tile for tile in self.config.get("tiles", []) if tile["id"] != widget.tile["id"]
        ]
        config_mod.save(self.config)
        self._refresh_tiles()

    # -- power / user menus ---------------------------------------------
    def _show_power_menu(self, button: Gtk.Button) -> None:
        menu = Gtk.Menu()
        for label, action in POWER_ACTIONS:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, a=action: _power_action(a))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _show_user_menu(self, button: Gtk.Button) -> None:
        menu = Gtk.Menu()
        header = Gtk.MenuItem(label=self._display_user())
        header.set_sensitive(False)
        menu.append(header)
        menu.append(Gtk.SeparatorMenuItem())
        for label, action in (("锁定", "LOCK"), ("注销", "LOGOUT"), ("关机", "SHUTDOWN")):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, a=action: _power_action(a))
            menu.append(item)
        settings = Gtk.MenuItem(label="账户设置")
        settings.connect("activate", lambda _i: self._open_account_settings())
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(settings)
        if self.config.get("hidden"):
            restore = Gtk.MenuItem(label="恢复隐藏的应用")
            restore.connect("activate", lambda _i: self._unhide_all())
            menu.append(restore)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _open_account_settings(self) -> None:
        for candidate in ("lxqt-admin-user", "mugshot", "xfce4-settings-manager"):
            if _which(candidate):
                _run([candidate])
                return

    def _open_system_settings(self) -> None:
        for candidate in (
            "lxqt-config",
            "xfce4-settings-manager",
            "systemsettings",
            "gnome-control-center",
        ):
            if _which(candidate):
                _run([candidate])
                self.request_hide()
                return

    # ------------------------------------------------------------------
    # window behaviour
    # ------------------------------------------------------------------
    def _on_show(self, _widget) -> None:
        self._position()
        self.all_apps_mode = False
        self.query = ""
        self.search.set_text("")
        self.menu_button.set_tooltip_text("所有应用")
        # Populate after the window has been mapped so the first paint is
        # immediate (the rail, search box and empty panes appear at once, the
        # lists and tiles fill in a moment later).  This mirrors the way
        # Whisker Menu loads its contents asynchronously.
        GLib.idle_add(self._populate)
        GLib.idle_add(self.search.grab_focus)

    def _position(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        anchor = getattr(self.application, "anchor", None)
        if anchor is not None:
            ax, ay, aw, ah = anchor
        else:
            pointer = display.get_default_seat().get_pointer()
            _screen, ax, ay = pointer.get_position()
            aw = ah = 0
        monitor = display.get_monitor_at_point(ax, ay) or display.get_primary_monitor()
        geometry = monitor.get_geometry()
        workarea = monitor.get_workarea()

        width = min(self.config["width"], workarea.width)
        height = min(self.config["height"], workarea.height)
        self.set_default_size(width, self.config["height"])

        if anchor is not None:
            # Place the menu next to the panel button it was launched from:
            # above it when the panel is at the bottom, below otherwise.
            x = max(workarea.x, min(ax, workarea.x + workarea.width - width))
            if ay + ah // 2 > geometry.height // 2:
                y = ay - height
            else:
                y = ay + ah
            y = max(workarea.y, min(y, workarea.y + workarea.height - height))
            self.move(x, y)
            return

        # No anchor: classic Windows position, bottom-left of the monitor.
        x = workarea.x + 8 if geometry.width > workarea.width else workarea.x
        y = workarea.y + workarea.height - height
        self.move(x, y)

    def request_hide(self) -> None:
        """Hide the menu and, unless keep_alive is set, quit the process."""
        self.hide()
        if not self.config.get("keep_alive", False):
            self.application.quit()

    def _on_delete(self, _widget, _event) -> bool:
        self.request_hide()
        return True

    def _on_focus_out(self, _widget, _event) -> bool:
        if Gtk.grab_get_current() is not None:
            return False
        # Give a panel-button toggle a moment to arrive before auto-closing.
        GLib.timeout_add(250, self._hide_if_unfocused)
        return False

    def _hide_if_unfocused(self) -> bool:
        if self.get_visible() and not self.is_active() and Gtk.grab_get_current() is None:
            self.request_hide()
        return False

    def _on_key_press(self, _widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.request_hide()
            return True
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up) and not self.search.has_focus():
            return self._move_selection(1 if event.keyval == Gdk.KEY_Down else -1)
        # Start typing from anywhere focuses the search box.
        if not self.search.has_focus():
            unicode_char = chr(event.keyval) if 0 < event.keyval < 0x110000 else ""
            if unicode_char.isprintable() and not (event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK)):
                self.search.grab_focus()
                self.search.set_text(self.search.get_text() + unicode_char)
                self.search.set_position(-1)
                return True
        return False

    # -- helpers --------------------------------------------------------
    def _display_user(self) -> str:
        name = self.config.get("user_name")
        if name:
            return name
        try:
            return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0] or getpass.getuser()
        except Exception:
            return getpass.getuser()

    def _load_avatar(self, size: int) -> GdkPixbuf.Pixbuf | None:
        avatar = self.config.get("avatar")
        if avatar and os.path.exists(avatar):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(avatar, size, size, True)
            except Exception:
                pass
        for candidate in ("~/.face", "~/.face.icon"):
            path = os.path.expanduser(candidate)
            if os.path.exists(path):
                try:
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
                except Exception:
                    pass
        theme = Gtk.IconTheme.get_default()
        for icon_name in ("avatar-default", "user-info", "user-home"):
            try:
                info = theme.lookup_icon(icon_name, size, 0)
            except Exception:
                info = None
            if info is not None:
                try:
                    return info.load_icon()
                except Exception:
                    continue
        return None
