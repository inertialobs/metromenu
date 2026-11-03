"""Gtk.Application wrapper for the start menu."""

from __future__ import annotations

import os
import sys

from . import desktop as desktop_mod  # stdlib only - must precede "import gi"
from . import timing  # noqa: E402  (starts the startup timer as early as possible)

# GDK latches GDK_SCALE the moment its typelib is imported, so the scale has to
# be chosen *before* ``import gi``.  Only LXQt (or an explicit METROMENU_SCALE)
# needs this fallback: it has no XSETTINGS daemon and advertises its scaling
# through Xft.dpi, which GTK uses for fonts but not for widget/tile sizes.
# Desktops with XSETTINGS (Xfce, GNOME, ...) already provide an integer
# Gdk/WindowScalingFactor, and overriding it with a DPI-derived GDK_SCALE would
# turn font-only scaling into full window scaling.
if not os.environ.get("GDK_SCALE"):
    if os.environ.get("METROMENU_SCALE") or desktop_mod.is_lxqt():
        _scale = desktop_mod.detect_scale()
        if _scale > 1:
            os.environ["GDK_SCALE"] = str(_scale)

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import apps as apps_mod  # noqa: E402
from . import config as config_mod  # noqa: E402
from .window import StartMenuWindow  # noqa: E402

timing.log("modules imported")

APP_ID = "org.metromenu.MetroMenu"
STYLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")


class StartMenuApplication(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.registry: apps_mod.AppRegistry | None = None
        self.config: dict = {}
        self.window: StartMenuWindow | None = None
        # Optional screen anchor (x, y, w, h) supplied by the panel plugin.
        self.anchor: tuple[int, int, int, int] | None = None
        self.no_cache = False

    # -- lifecycle ------------------------------------------------------
    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self._load_css()
        timing.log("gtk startup + css")
        self.set_accels_for_action("app.quit", ["<Primary>q"])
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(STYLE_PATH)
        except GLib.Error as error:
            print(f"metromenu: could not load style sheet: {error}", file=sys.stderr)
            return
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def do_activate(self) -> None:
        if self.registry is None:
            self.registry = apps_mod.AppRegistry(use_cache=not self.no_cache)
            timing.log(f"registry ready ({len(self.registry.apps)} apps)")
        if self.window is None:
            if not self.config:
                self.config = config_mod.load([a.desktop_id for a in self.registry.apps])
            self.window = StartMenuWindow(self, self.registry, self.config)
            self.window.set_application(self)
            timing.log("window built")
        self.toggle()

    def do_command_line(self, command_line) -> int:
        for argument in command_line.get_arguments()[1:]:
            if argument.startswith("--anchor="):
                self.anchor = _parse_anchor(argument.split("=", 1)[1])
            elif argument == "--no-cache":
                self.no_cache = True
        self.do_activate()
        return 0

    def toggle(self) -> None:
        window = self.window
        if window is None:
            return
        # Only look at visibility: when the panel button is clicked the window
        # loses focus first, so is_active() would wrongly report it as closed.
        if window.get_visible():
            window.request_hide()
        else:
            window.show_all()
            window.present()
            gdk_window = window.get_window()
            if gdk_window is not None:
                gdk_window.focus(Gdk.CURRENT_TIME)


def _parse_anchor(value: str) -> tuple[int, int, int, int] | None:
    try:
        parts = [int(p) for p in value.split(",")]
    except ValueError:
        return None
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]


def main(argv: list[str] | None = None) -> int:
    application = StartMenuApplication()
    return application.run(argv if argv is not None else sys.argv)
