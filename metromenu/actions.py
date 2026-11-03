"""Desktop actions used by the start menu context menus.

These wrap the small Linux-specific operations that do not belong in the
widget code: revealing a desktop file, editing it, copying the launch command,
adding a shortcut to the desktop and adding a launcher to the panel (Xfce via
xfconf, LXQt via ``~/.config/lxqt/panel.conf``).
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import desktop  # noqa: E402


def _which(program: str) -> str | None:
    return shutil.which(program)


def _spawn(argv: list[str]) -> None:
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


def desktop_directory() -> Path:
    special = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
    if special:
        return Path(special)
    return Path(os.path.expanduser("~/Desktop"))


def reveal_file(path: Path) -> bool:
    """Show ``path`` in the file manager (selecting it when supported)."""
    try:
        uri = Gio.File.new_for_path(str(path)).get_uri()
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        connection.call_sync(
            "org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1",
            "ShowItems",
            GLib.Variant("(ass)", ([uri], "")),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        return True
    except GLib.Error:
        pass
    # Fall back to opening the containing directory.
    parent = str(path.parent)
    for manager in ("pcmanfm-qt", "thunar", "nemo", "nautilus", "dolphin", "pcmanfm", "caja", "xdg-open"):
        if _which(manager):
            _spawn([manager, parent])
            return True
    return False


def edit_file(path: Path) -> bool:
    for editor in ("featherpad", "mousepad", "gedit", "kate", "xed", "xdg-open"):
        if _which(editor):
            _spawn([editor, str(path)])
            return True
    return False


def copy_text(text: str) -> None:
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_text(text, -1)
    clipboard.store()


def add_to_desktop(desktop_file: Path) -> bool:
    """Copy a .desktop entry to the user's desktop directory."""
    target_dir = desktop_directory()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / desktop_file.name
        shutil.copyfile(desktop_file, target)
        os.chmod(target, 0o755)
        # Mark it trusted so file managers do not refuse to run it.
        try:
            Gio.File.new_for_path(str(target)).set_attribute_string(
                "metadata::trusted", "yes"
            )
        except Exception:
            pass
        return True
    except OSError:
        return False


def _xfconf_get(*args: str) -> str:
    try:
        result = subprocess.run(
            ["xfconf-query", *args], capture_output=True, text=True, timeout=5
        )
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _xfconf_set(args: list[str]) -> bool:
    try:
        subprocess.run(["xfconf-query", *args], capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _add_launcher_to_xfce_panel(desktop_file: Path, panel: int = 1) -> bool:
    """Register a launcher item for ``desktop_file`` on an Xfce panel."""
    if not _which("xfconf-query"):
        return False

    # Find the next free plugin id.
    listing = _xfconf_get("-c", "xfce4-panel", "-p", "/plugins", "-l")
    max_id = 0
    for line in listing.splitlines():
        name = line.rsplit("plugin-", 1)[-1]
        if name.isdigit():
            max_id = max(max_id, int(name))
    plugin_id = max_id + 1

    launcher_dir = Path.home() / ".config/xfce4/panel" / f"launcher-{plugin_id}"
    try:
        launcher_dir.mkdir(parents=True, exist_ok=True)
        item_name = f"metromenu-{int(time.time())}-{os.getpid()}.desktop"
        shutil.copyfile(desktop_file, launcher_dir / item_name)
    except OSError:
        return False

    if not _xfconf_set(
        ["-c", "xfce4-panel", "-p", f"/plugins/plugin-{plugin_id}", "-n", "-t", "string", "-s", "launcher"]
    ):
        return False
    _xfconf_set(
        ["-c", "xfce4-panel", "-p", f"/plugins/plugin-{plugin_id}/items", "-n", "-t", "string", "-s", item_name]
    )

    # Append the plugin to the panel's list.
    current = _xfconf_get("-c", "xfce4-panel", "-p", f"/panels/panel-{panel}/plugin-ids", "-v")
    ids = [line for line in current.splitlines() if line.strip().isdigit()]
    args = ["-c", "xfce4-panel", "-p", f"/panels/panel-{panel}/plugin-ids"]
    for value in [*ids, str(plugin_id)]:
        args += ["-t", "int", "-s", value]
    _xfconf_set(args)

    _spawn(["xfce4-panel", "--restart"])
    return True


# --------------------------------------------------------------------------
# LXQt panel integration
#
# The LXQt panel does not read xfconf; its configuration is a plain INI file
# (``~/.config/lxqt/panel.conf``) that the running panel watches and reloads.
# Panel buttons come from the "Custom Command" plugin, so adding an item means
# appending a plugin section and listing its name under the panel's ``plugins``
# key.
# --------------------------------------------------------------------------
def _lxqt_panel_conf() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(config_home) / "lxqt" / "panel.conf"


def _desktop_entry_value(desktop_file: Path, key: str) -> str:
    try:
        keyfile = GLib.KeyFile()
        keyfile.load_from_file(str(desktop_file), GLib.KeyFileFlags.NONE)
        return keyfile.get_string("Desktop Entry", key)
    except GLib.Error:
        return ""


def _desktop_exec(desktop_file: Path) -> str:
    """The launch command of a .desktop file with ``%`` field codes removed."""
    exec_ = _desktop_entry_value(desktop_file, "Exec")
    return " ".join(part for part in exec_.split() if not part.startswith("%"))


def add_command_to_lxqt_panel(
    command: str,
    icon: str = "",
    text: str = "",
    name: str = "metromenu",
    panel: int = 1,
) -> bool:
    """Add an LXQt panel "Custom Command" widget that runs ``command``.

    ``name`` is the widget identifier inside ``panel.conf``; re-adding the same
    command reuses the existing entry instead of stacking duplicates.
    """
    conf_path = _lxqt_panel_conf()
    if not conf_path.exists():
        return False

    parser = configparser.RawConfigParser()
    parser.optionxform = str  # keep key case (LXQt is case sensitive)
    try:
        with conf_path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error):
        return False

    panel_section = f"panel{panel}"
    if not parser.has_section(panel_section):
        return False

    # Unique section name, reused when it already runs the same command.
    plugin_name = name
    suffix = 2
    while parser.has_section(plugin_name) and parser.get(plugin_name, "command", fallback=None) != command:
        plugin_name = f"{name}{suffix}"
        suffix += 1

    if not parser.has_section(plugin_name):
        parser.add_section(plugin_name)
    parser.set(plugin_name, "type", "customcommand")
    parser.set(plugin_name, "alignment", "Left")
    parser.set(plugin_name, "command", command)
    if icon:
        parser.set(plugin_name, "icon", icon)
    if text:
        parser.set(plugin_name, "text", text)

    plugins = [p.strip() for p in parser.get(panel_section, "plugins", fallback="").split(",") if p.strip()]
    if plugin_name not in plugins:
        plugins.insert(0, plugin_name)  # place the button at the far left
    parser.set(panel_section, "plugins", ", ".join(plugins))

    try:
        tmp = conf_path.with_suffix(".conf.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            parser.write(handle)
            handle.write("\n")
        tmp.replace(conf_path)
    except OSError:
        return False
    return True


def _add_desktop_launcher_to_lxqt_panel(desktop_file: Path, panel: int = 1) -> bool:
    command = _desktop_exec(desktop_file)
    if not command:
        return False
    icon = _desktop_entry_value(desktop_file, "Icon")
    return add_command_to_lxqt_panel(
        command, icon=icon, text="", name="metromenu-app", panel=panel
    )


def add_launcher_to_panel(desktop_file: Path, panel: int = 1) -> bool:
    """Add a launcher for ``desktop_file`` to the running session's panel."""
    if desktop.is_lxqt() or (_which("lxqt-panel") and not _which("xfce4-panel")):
        return _add_desktop_launcher_to_lxqt_panel(desktop_file, panel)
    return _add_launcher_to_xfce_panel(desktop_file, panel)
