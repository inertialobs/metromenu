"""Desktop-environment detection and command resolution.

metromenu started life as an Xfce start menu, so a handful of places used to
hard-code Xfce programs (``xfce4-session-logout``, ``xfconf-query`` ...) and the
``XFCE`` desktop name.  These helpers let the same code live on LXQt (or any
other freedesktop desktop) by looking at the running session at runtime.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess


def which(program: str) -> str | None:
    """Return the path of ``program`` if it is executable, else ``None``."""
    return shutil.which(program)


def current_desktops() -> set[str]:
    """The desktop names advertised by the session, upper-cased.

    ``XDG_CURRENT_DESKTOP`` is a colon separated list such as ``XFCE`` or
    ``LXQt``; the other two variables carry a single name.  The result is used
    to honour the ``OnlyShowIn`` / ``NotShowIn`` keys of ``.desktop`` files.
    """
    names: set[str] = set()
    for variable in (
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_DESKTOP",
        "DESKTOP_SESSION",
    ):
        value = os.environ.get(variable) or ""
        for part in value.replace(";", ":").split(":"):
            part = part.strip()
            if part:
                names.add(part.upper())
    return names


def is_lxqt() -> bool:
    """Whether the session is an LXQt desktop."""
    return "LXQT" in current_desktops()


def first_available(candidates: list[list[str]] | None) -> list[str] | None:
    """Return the first argument vector whose program exists on ``PATH``.

    ``None`` entries are ignored, which makes it easy to build a preference
    list where a desktop specific command is optional.
    """
    for argv in candidates or []:
        if argv and which(argv[0]):
            return argv
    return None


@functools.lru_cache(maxsize=1)
def session_dpi() -> float:
    """The DPI the session advertises through the ``Xft.dpi`` X resource.

    The result is cached: querying it spawns ``xrdb``, and the resource does
    not change while the menu process lives.
    """
    try:
        result = subprocess.run(
            ["xrdb", "-query"], capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    for line in result.stdout.splitlines():
        name, _, value = line.partition(":")
        if name.strip().lower() == "xft.dpi":
            try:
                return float(value.strip())
            except ValueError:
                return 0.0
    return 0.0


def detect_scale() -> int:
    """Suggested integer UI scale for this session.

    GTK only selects an integer HiDPI scale automatically from the
    ``Gdk/WindowScalingFactor`` XSETTINGS value.  LXQt does not run an XSETTINGS
    daemon, so it advertises its scaling through ``Xft.dpi`` (typically 192 on a
    2x desktop) instead - which GTK uses for fonts but not for widget/tile
    sizes.  Reading it here lets metromenu match the rest of the desktop.

    An explicit ``METROMENU_SCALE`` or ``GDK_SCALE`` in the environment always
    wins, so the behaviour can be overridden.
    """
    for variable in ("METROMENU_SCALE", "GDK_SCALE"):
        value = os.environ.get(variable)
        if value:
            try:
                return max(1, int(float(value)))
            except ValueError:
                pass

    dpi = session_dpi()
    if dpi <= 0:
        return 1
    # GTK scaling is integer-only; round to the nearest step from 96 DPI.
    return max(1, int(round(dpi / 96.0)))
