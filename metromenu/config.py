"""Configuration handling for the Windows 10 style start menu.

The configuration lives in ``$XDG_CONFIG_HOME/metromenu/config.json`` and
stores the layout of the tile area, the pinned applications and a few visual
settings.  Everything is treated as user editable - the file is plain JSON.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_NAME = "metromenu"

_CONF_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONFIG_FILE = Path(_CONF_HOME) / APP_NAME / "config.json"

# Tile sizes expressed in grid cells.  This mirrors the Windows 10 tile system.
TILE_SIZES = {
    "small": (1, 1),
    "medium": (2, 2),
    "wide": (4, 2),
    "large": (4, 4),
}

# The base size of a single tile cell in pixels.  Used to compute the fixed
# pixel sizes handed to the icon loader and to the CSS classes.
CELL = 48

SIZE_PIXELS = {
    "small": (CELL, CELL),
    "medium": (CELL * 2, CELL * 2),
    "wide": (CELL * 4, CELL * 2),
    "large": (CELL * 4, CELL * 4),
}

SIZE_ICONS = {
    "small": 24,
    "medium": 40,
    "wide": 40,
    "large": 56,
}

# A palette of Metro accent colours used for the default tiles.
PALETTE = [
    "#0078d7",  # windows blue
    "#2d7d9a",
    "#00aba9",
    "#2d89ef",
    "#1e7145",
    "#da532c",
    "#b91d47",
    "#6a00ff",
    "#d24726",
    "#8c0095",
    "#008a00",
    "#0050ef",
    "#a20025",
    "#647687",
]

# Applications that get promoted to the default set of pinned tiles, in order.
# Only entries whose desktop file actually exists are used.  The list is
# LXQt-first (metromenu's primary target) with the common cross-desktop apps
# and the original Xfce candidates kept as a fallback.
DEFAULT_TILE_CANDIDATES = [
    "firefox-esr.desktop",
    "firefox.desktop",
    "chromium.desktop",
    "google-chrome.desktop",
    "org.gnome.Epiphany.desktop",
    "pcmanfm-qt.desktop",
    "qterminal.desktop",
    "featherpad.desktop",
    "lximage-qt.desktop",
    "lxqt-archiver.desktop",
    "qps.desktop",
    "pavucontrol-qt.desktop",
    "lxqt-config.desktop",
    "obconf-qt.desktop",
    "code.desktop",
    "com.microsoft.VSCode.desktop",
    "libreoffice-writer.desktop",
    "libreoffice-calc.desktop",
    "libreoffice-impress.desktop",
    "vlc.desktop",
    "org.kde.kolourpaint.desktop",
    "org.kde.kcalc.desktop",
    "org.gnome.SystemMonitor.desktop",
    "io.github.quodlibet.QuodLibet.desktop",
    "org.pulseaudio.pavucontrol.desktop",
    # Xfce fallbacks, so an Xfce session keeps its previous defaults.
    "thunar.desktop",
    "xfce4-terminal.desktop",
    "org.xfce.mousepad.desktop",
    "xfce4-settings-manager.desktop",
    "xfce4-screenshooter.desktop",
    "org.xfce.Parole.desktop",
    "org.xfce.ristretto.desktop",
]

DEFAULT_GROUPS = ["效率", "媒体与娱乐", "实用工具"]


def _default_tiles(available_ids: list[str]) -> list[dict]:
    """Pick a reasonable starting set of tiles from the installed apps."""
    available = set(available_ids)
    chosen: list[str] = []
    for desktop_id in DEFAULT_TILE_CANDIDATES:
        if desktop_id in available and desktop_id not in chosen:
            chosen.append(desktop_id)

    # Fall back to the first apps we can find when nothing matched.
    if not chosen:
        chosen = sorted(available)[:12]

    tiles: list[dict] = []
    for index, desktop_id in enumerate(chosen[:15]):
        size = "medium"
        if index == 0:
            size = "wide"
        elif index in (5, 6):
            size = "wide"
        group = DEFAULT_GROUPS[min(index // 5, len(DEFAULT_GROUPS) - 1)]
        tiles.append(
            {
                "id": desktop_id,
                "size": size,
                "group": group,
                "color": PALETTE[index % len(PALETTE)],
            }
        )
    return tiles


def default_config(available_ids: list[str] | None = None) -> dict:
    return {
        "version": 1,
        "accent": "#0078d7",
        "background": "#1b1b1b",
        "opacity": 0.96,
        "width": 680,
        "height": 672,
        "left_width": 312,
        "avatar": "",
        "user_name": "",
        "groups": list(DEFAULT_GROUPS),
        "pinned": [],
        "tiles": _default_tiles(available_ids or []),
        "show_recent": True,
        "keep_alive": False,
        "hidden": [],
    }


def load(available_ids: list[str] | None = None) -> dict:
    """Load the config, creating it with sensible defaults on first run."""
    config = default_config(available_ids)
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                config = _merge(config, stored)
        except (OSError, ValueError):
            # A broken config should never stop the menu from opening.
            pass
    return config


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def save(config: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(CONFIG_FILE)
