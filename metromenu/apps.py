"""Discovery, search and launching of freedesktop applications.

The module intentionally avoids ``Gio.AppInfo`` for discovery so that the menu
behaves the same on every desktop: entries are read straight from the XDG
application directories, which gives us access to categories, keywords and
desktop actions.  Launching uses ``Gio.Subprocess`` so we can honour ``Path``,
``Terminal`` and the ``%`` field codes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import desktop  # noqa: E402


# Cache of the parsed application list, so a cold start does not have to read
# and parse every .desktop file again.  The cache stores a fingerprint of the
# .desktop files (path + mtime + size); whenever software is installed, removed
# or updated the fingerprint changes and the list is scanned again.  A generous
# TTL is only a safety net in case a filesystem does not report mtimes.
CACHE_VERSION = 3
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
CACHE_FILE = Path(_CACHE_HOME) / "metromenu" / "apps.json"


TERMINALS = [
    "x-terminal-emulator",
    "xfce4-terminal",
    "gnome-terminal",
    "konsole",
    "alacritty",
    "kitty",
    "tilix",
    "mate-terminal",
    "lxterminal",
    "qterminal",
    "xterm",
]

# Terminal specific flags used to run a command inside the emulator.
TERMINAL_EXEC_FLAGS = {
    "qterminal": ["-e"],
    "xfce4-terminal": ["-x"],
    "gnome-terminal": ["--"],
    "tilix": ["-e"],
    "konsole": ["-e"],
    "alacritty": ["-e"],
    "kitty": [],
    "mate-terminal": ["-x"],
    "lxterminal": ["-e"],
    "x-terminal-emulator": ["-e"],
    "xterm": ["-e"],
}

# Per-desktop terminal preferences, tried before the generic list so that
# installing another desktop's terminal does not change the default here.
PREFERRED_TERMINALS = {
    "XFCE": ["xfce4-terminal"],
    "LXQT": ["qterminal", "lxterminal"],
    "MATE": ["mate-terminal"],
    "KDE": ["konsole"],
    "GNOME": ["gnome-terminal"],
}


def _terminal_candidates() -> list[str]:
    preferred: list[str] = []
    for name in sorted(desktop.current_desktops()):
        for candidate in PREFERRED_TERMINALS.get(name, []):
            if candidate not in preferred:
                preferred.append(candidate)
    return [*preferred, *(candidate for candidate in TERMINALS if candidate not in preferred)]


def _desktop_dirs() -> list[Path]:
    dirs: list[Path] = []
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs.append(Path(data_home) / "applications")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for entry in data_dirs.split(":"):
        if entry:
            dirs.append(Path(entry) / "applications")
    return dirs


def _cache_signature() -> dict:
    """A cheap fingerprint of every .desktop file plus the current locale.

    Hashing the file list (path + mtime + size) means any install, removal or
    in-place update of a desktop file invalidates the cache, so a newly
    installed application shows up the next time the menu opens.  This only
    stats the files - it never parses them - so it is far cheaper than a full
    scan.
    """
    digest = hashlib.sha1()
    for directory in _desktop_dirs():
        if not directory.is_dir():
            continue
        try:
            paths = sorted(directory.rglob("*.desktop"))
        except OSError:
            continue
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{path}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode("utf-8", "replace"))
    locale = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    # The desktop name is part of the signature: OnlyShowIn/NotShowIn filtering
    # depends on it, so switching desktops (or changing XDG_CURRENT_DESKTOP)
    # must invalidate the cache instead of serving a list built for another DE.
    return {
        "version": CACHE_VERSION,
        "locale": locale,
        "desktops": sorted(desktop.current_desktops()),
        "files": digest.hexdigest(),
    }


def normalize(text: str) -> str:
    """Case/diacritic insensitive normalisation used for searching."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold()


def _clean(value: str | None) -> str:
    return value.strip() if value else ""


@dataclass
class DesktopAction:
    key: str
    name: str
    exec_: str
    icon: str = ""

    def to_cache(self) -> dict:
        return {"key": self.key, "name": self.name, "exec": self.exec_, "icon": self.icon}

    @classmethod
    def from_cache(cls, data: dict) -> "DesktopAction":
        return cls(
            key=data.get("key", ""),
            name=data.get("name", ""),
            exec_=data.get("exec", ""),
            icon=data.get("icon", ""),
        )


@dataclass
class DesktopApp:
    desktop_id: str
    path: Path
    name: str
    generic_name: str = ""
    comment: str = ""
    icon: str = ""
    exec_: str = ""
    terminal: bool = False
    working_dir: str = ""
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    wm_class: str = ""
    actions: list[DesktopAction] = field(default_factory=list)
    dbus_activatable: bool = False
    startup_notify: bool = False

    # pre-computed search haystacks
    _search_name: str = field(default="", repr=False)
    _search_generic: str = field(default="", repr=False)
    _search_comment: str = field(default="", repr=False)
    _search_keywords: list[str] = field(default_factory=list, repr=False)
    _search_exec: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        self._search_name = normalize(self.name)
        self._search_generic = normalize(self.generic_name)
        self._search_comment = normalize(self.comment)
        self._search_keywords = [normalize(k) for k in self.keywords if k]
        command = self.exec_.split(" ", 1)[0]
        self._search_exec = normalize(os.path.basename(command))

    # -- (de)serialisation for the on-disk cache ------------------------
    def to_cache(self) -> dict:
        return {
            "desktop_id": self.desktop_id,
            "path": str(self.path),
            "name": self.name,
            "generic_name": self.generic_name,
            "comment": self.comment,
            "icon": self.icon,
            "exec": self.exec_,
            "terminal": self.terminal,
            "working_dir": self.working_dir,
            "categories": self.categories,
            "keywords": self.keywords,
            "wm_class": self.wm_class,
            "actions": [action.to_cache() for action in self.actions],
            "dbus_activatable": self.dbus_activatable,
            "startup_notify": self.startup_notify,
        }

    @classmethod
    def from_cache(cls, data: dict) -> "DesktopApp":
        return cls(
            desktop_id=data.get("desktop_id", ""),
            path=Path(data.get("path", "")),
            name=data.get("name", ""),
            generic_name=data.get("generic_name", ""),
            comment=data.get("comment", ""),
            icon=data.get("icon", ""),
            exec_=data.get("exec", ""),
            terminal=bool(data.get("terminal", False)),
            working_dir=data.get("working_dir", ""),
            categories=list(data.get("categories", [])),
            keywords=list(data.get("keywords", [])),
            wm_class=data.get("wm_class", ""),
            actions=[DesktopAction.from_cache(a) for a in data.get("actions", [])],
            dbus_activatable=bool(data.get("dbus_activatable", False)),
            startup_notify=bool(data.get("startup_notify", False)),
        )

    # -- search ---------------------------------------------------------
    def score(self, query: str) -> int | None:
        """Return a relevance score (lower is better) or ``None`` if no match."""
        if not query:
            return 0
        norm = query.casefold()
        best: int | None = None

        def consider(haystack: str, weight: int) -> None:
            nonlocal best
            if not haystack:
                return
            index = haystack.find(norm)
            if index < 0:
                return
            score = weight + index
            if index == 0:
                score -= 100
            if best is None or score < best:
                best = score

        consider(self._search_name, 0)
        consider(self._search_generic, 200)
        consider(self._search_comment, 300)
        for keyword in self._search_keywords:
            consider(keyword, 150)
        consider(self._search_exec, 400)
        return best

    def matches(self, query: str) -> bool:
        return self.score(query) is not None


class AppRegistry:
    """Caches the installed applications and their desktop files."""

    def __init__(self, use_cache: bool = True) -> None:
        self.apps: list[DesktopApp] = []
        self.by_id: dict[str, DesktopApp] = {}
        self.use_cache = use_cache
        self.reload()

    # -- discovery ------------------------------------------------------
    def reload(self) -> None:
        if self.use_cache and self._load_from_cache():
            return
        apps = self._scan()
        self._set_apps(apps)
        if self.use_cache:
            self._save_to_cache(apps)

    def _scan(self) -> list[DesktopApp]:
        apps: list[DesktopApp] = []
        seen: set[str] = set()
        # Inspect the environment once per scan instead of once per .desktop
        # file (there are usually hundreds of them).
        desktops = desktop.current_desktops()
        for directory in _desktop_dirs():
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.desktop")):
                desktop_id = self._make_id(directory, path)
                if desktop_id in seen:
                    continue
                app = self._parse(desktop_id, path, desktops)
                if app is not None:
                    seen.add(desktop_id)
                    apps.append(app)
        apps.sort(key=lambda a: normalize(a.name))
        return apps

    def _set_apps(self, apps: list[DesktopApp]) -> None:
        self.apps = apps
        self.by_id = {app.desktop_id: app for app in apps}

    # -- on-disk cache --------------------------------------------------
    def _load_from_cache(self) -> bool:
        try:
            with CACHE_FILE.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict) or data.get("signature") != _cache_signature():
            return False
        created = data.get("created", 0)
        if time.time() - created > CACHE_TTL_SECONDS:
            return False
        try:
            apps = [DesktopApp.from_cache(item) for item in data.get("apps", [])]
        except (TypeError, ValueError, KeyError):
            return False
        if not apps:
            return False
        self._set_apps(apps)
        return True

    def _save_to_cache(self, apps: list[DesktopApp]) -> None:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE_FILE.with_suffix(".json.tmp")
            payload = {
                "signature": _cache_signature(),
                "created": time.time(),
                "apps": [app.to_cache() for app in apps],
            }
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            tmp.replace(CACHE_FILE)
        except OSError:
            pass

    @staticmethod
    def _make_id(directory: Path, path: Path) -> str:
        try:
            relative = path.relative_to(directory)
        except ValueError:
            return path.name
        # The freedesktop desktop file id keeps the .desktop suffix and uses
        # dashes instead of directory separators.
        return str(relative).replace(os.sep, "-")

    def _parse(
        self, desktop_id: str, path: Path, desktops: set[str] | None = None
    ) -> DesktopApp | None:
        keyfile = GLib.KeyFile()
        try:
            keyfile.load_from_file(str(path), GLib.KeyFileFlags.NONE)
        except GLib.Error:
            return None

        group = "Desktop Entry"
        if not keyfile.has_group(group):
            return None

        def get(key: str, localized: bool = False) -> str:
            try:
                if localized:
                    value = keyfile.get_locale_string(group, key)
                else:
                    value = keyfile.get_string(group, key)
            except GLib.Error:
                return ""
            return _clean(value)

        try:
            if get("Type") != "Application":
                return None
        except Exception:
            return None

        if get("Hidden").lower() == "true":
            return None
        if get("NoDisplay").lower() == "true":
            return None

        # Honour OnlyShowIn / NotShowIn against the *running* desktop instead
        # of assuming Xfce, so the menu also works on LXQt and friends.  When
        # the session does not advertise a desktop name we skip the filter
        # rather than hiding everything.
        desktops = desktops if desktops is not None else desktop.current_desktops()
        if desktops:
            only_show = get("OnlyShowIn")
            if only_show:
                entries = {e.strip().upper() for e in only_show.split(";") if e.strip()}
                if entries and not (entries & desktops):
                    return None
            not_show = get("NotShowIn")
            if not_show:
                entries = {e.strip().upper() for e in not_show.split(";") if e.strip()}
                if entries & desktops:
                    return None

        exec_ = get("Exec")
        if not exec_:
            return None

        try_exec = get("TryExec")
        if try_exec and not self._executable_exists(try_exec):
            return None

        name = get("Name", localized=True) or get("Name")
        if not name:
            return None

        keywords = []
        try:
            keywords = [k.strip() for k in keyfile.get_string_list(group, "Keywords") if k.strip()]
        except GLib.Error:
            pass

        categories = []
        raw_categories = get("Categories")
        if raw_categories:
            categories = [c for c in raw_categories.split(";") if c]

        actions: list[DesktopAction] = []
        raw_actions = get("Actions")
        if raw_actions:
            for action_key in [a for a in raw_actions.split(";") if a]:
                action_group = f"Desktop Action {action_key}"
                if not keyfile.has_group(action_group):
                    continue
                try:
                    action_name = keyfile.get_locale_string(action_group, "Name")
                except GLib.Error:
                    try:
                        action_name = keyfile.get_string(action_group, "Name")
                    except GLib.Error:
                        action_name = action_key
                try:
                    action_exec = keyfile.get_string(action_group, "Exec")
                except GLib.Error:
                    continue
                try:
                    action_icon = keyfile.get_string(action_group, "Icon")
                except GLib.Error:
                    action_icon = ""
                actions.append(
                    DesktopAction(
                        key=action_key,
                        name=_clean(action_name),
                        exec_=action_exec,
                        icon=_clean(action_icon),
                    )
                )

        return DesktopApp(
            desktop_id=desktop_id,
            path=path,
            name=name,
            generic_name=get("GenericName", localized=True) or get("GenericName"),
            comment=get("Comment", localized=True) or get("Comment"),
            icon=get("Icon", localized=True) or get("Icon"),
            exec_=exec_,
            terminal=get("Terminal").lower() == "true",
            working_dir=get("Path"),
            categories=categories,
            keywords=keywords,
            wm_class=get("StartupWMClass"),
            actions=actions,
            dbus_activatable=get("DBusActivatable").lower() == "true",
            startup_notify=get("StartupNotify").lower() == "true",
        )

    @staticmethod
    def _executable_exists(program: str) -> bool:
        if os.path.isabs(program):
            return os.path.exists(program)
        return shutil.which(program) is not None

    # -- lookup ---------------------------------------------------------
    def get(self, desktop_id: str) -> DesktopApp | None:
        return self.by_id.get(desktop_id)

    def search(self, query: str, limit: int | None = None) -> list[DesktopApp]:
        norm = query.strip()
        if not norm:
            return list(self.apps[: limit] if limit else self.apps)
        scored: list[tuple[int, DesktopApp]] = []
        for app in self.apps:
            score = app.score(norm)
            if score is not None:
                scored.append((score, app))
        scored.sort(key=lambda item: (item[0], normalize(item[1].name)))
        result = [app for _, app in scored]
        return result[:limit] if limit else result


def find_terminal() -> str | None:
    requested = os.environ.get("TERMINAL")
    if requested and shutil.which(requested):
        return requested
    for candidate in _terminal_candidates():
        if shutil.which(candidate):
            return candidate
    return None


def expand_field_codes(command: str, app: DesktopApp, action: DesktopAction | None = None) -> list[str]:
    """Expand the freedesktop ``%`` field codes into an argv list."""
    icon = action.icon if action and action.icon else app.icon
    name = action.name if action else app.name
    try:
        argv = GLib.shell_parse_argv(command)[1]
    except GLib.Error:
        return []

    expanded: list[str] = []
    for token in argv:
        token = token.replace("%%", "\0")
        has_icon = "%i" in token
        token = token.replace("%c", name)
        token = token.replace("%k", str(app.path))
        token = token.replace("%i", "")
        # Files/URLs: the menu launches applications without arguments.
        for code in ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%v", "%m"):
            token = token.replace(code, "")
        token = token.replace("\0", "%")
        if token == "" and not has_icon:
            continue
        if has_icon and icon:
            expanded.extend(["--icon", icon])
        if token:
            expanded.append(token)
    return expanded


def _resolve_program(program: str) -> str:
    """Return an absolute path for ``program`` when it can be found in PATH.

    Newer GLib releases dropped ``G_SUBPROCESS_FLAGS_SEARCH_PATH``, so we do
    the PATH lookup ourselves before spawning.
    """
    if os.path.isabs(program):
        return program
    found = shutil.which(program)
    return found or program


def launch(app: DesktopApp, action: DesktopAction | None = None) -> bool:
    """Spawn the application.  Returns ``True`` when the process started."""
    command = action.exec_ if action else app.exec_
    argv = expand_field_codes(command, app, action)
    if not argv:
        try:
            argv = GLib.shell_parse_argv(command)[1]
        except GLib.Error:
            return False
    if not argv:
        return False

    if action is None and app.terminal:
        terminal = find_terminal()
        if terminal:
            flags = TERMINAL_EXEC_FLAGS.get(os.path.basename(terminal), ["-e"])
            argv = [terminal, *flags, *argv]

    argv[0] = _resolve_program(argv[0])

    launcher = Gio.SubprocessLauncher.new(
        Gio.SubprocessFlags.STDOUT_SILENCE
        | Gio.SubprocessFlags.STDERR_SILENCE
        | Gio.SubprocessFlags.STDIN_INHERIT
    )
    if app.working_dir and os.path.isdir(app.working_dir):
        launcher.set_cwd(app.working_dir)
    try:
        launcher.spawnv(argv)
    except GLib.Error:
        return False
    return True
