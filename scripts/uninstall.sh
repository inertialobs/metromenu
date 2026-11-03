#!/usr/bin/env bash
# Remove the start menu.
#
# Usage:  ./scripts/uninstall.sh [--panel] [--hotkey] [--purge]
#   --panel    remove the panel launcher/widget (Xfce or LXQt)
#   --hotkey   remove keyboard shortcut(s) pointing at the menu
#   --purge    also delete the saved layout (~/.config/metromenu)
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
SHARE="$PREFIX/share"
APP_DIR="$SHARE/metromenu"
BIN_DIR="$PREFIX/bin"
BIN="$BIN_DIR/metromenu"
PANEL_DIR="${HOME}/.config/xfce4/panel"
CHANNEL="xfce4-panel"

WANT_PANEL=0
WANT_HOTKEY=0
WANT_PURGE=0
for arg in "$@"; do
    case "$arg" in
        --panel) WANT_PANEL=1 ;;
        --hotkey) WANT_HOTKEY=1 ;;
        --purge) WANT_PURGE=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

remove_panel_button() {
    command -v xfconf-query >/dev/null 2>&1 || return 0
    local removed=0

    # Launcher-plugin buttons created by integrate-panel.sh.
    for dir in "$PANEL_DIR"/launcher-*; do
        [[ -d "$dir" ]] || continue
        if grep -rqs "^Exec=$BIN\$" "$dir" 2>/dev/null; then
            local id="${dir##*/launcher-}"
            drop_plugin_id "$id"
            xfconf-query -c "$CHANNEL" -p "/plugins/plugin-$id" -r -R >/dev/null 2>&1 || true
            rm -rf "$dir"
            removed=1
        fi
    done

    # Native panel plugin created by install-panel-plugin.sh.
    while IFS= read -r line; do
        local id="${line#/plugins/plugin-}"
        [[ "$id" =~ ^[0-9]+$ ]] || continue
        if [[ "$(xfconf-query -c "$CHANNEL" -p "/plugins/plugin-$id" -v 2>/dev/null)" == "metromenu" ]]; then
            drop_plugin_id "$id"
            xfconf-query -c "$CHANNEL" -p "/plugins/plugin-$id" -r -R >/dev/null 2>&1 || true
            removed=1
        fi
    done < <(xfconf-query -c "$CHANNEL" -p /plugins -l 2>/dev/null | grep -E '^/plugins/plugin-[0-9]+$' || true)

    if [[ "$removed" == "1" ]]; then
        xfce4-panel --restart >/dev/null 2>&1 || true
        echo "Removed panel button(s)."
    fi
}

drop_plugin_id() {
    local id="$1" panel prop
    for panel in 1 2 3 4; do
        prop="/panels/panel-$panel/plugin-ids"
        xfconf-query -c "$CHANNEL" -p "$prop" >/dev/null 2>&1 || continue
        mapfile -t ids < <(xfconf-query -c "$CHANNEL" -p "$prop" -v | grep -E '^[0-9]+$' || true)
        local args=()
        for value in "${ids[@]}"; do
            [[ "$value" == "$id" ]] && continue
            args+=(-t int -s "$value")
        done
        [[ ${#args[@]} -gt 0 ]] && xfconf-query -c "$CHANNEL" -p "$prop" "${args[@]}" || true
    done
}

remove_hotkeys() {
    command -v xfconf-query >/dev/null 2>&1 || return 0
    while IFS= read -r prop; do
        [[ -n "$prop" ]] || continue
        xfconf-query -c xfce4-keyboard-shortcuts -p "$prop" -r >/dev/null 2>&1 || true
        echo "Removed shortcut $prop"
    done < <(xfconf-query -c xfce4-keyboard-shortcuts -p /commands/custom -l -v 2>/dev/null \
        | awk -v cmd="$BIN" '$NF == cmd { print $1 }')
}

remove_lxqt_panel_button() {
    local conf="${XDG_CONFIG_HOME:-$HOME/.config}/lxqt/panel.conf"
    [[ -f "$conf" ]] || return 0
    python3 - "$conf" <<'PY' || true
import configparser
import sys

path = sys.argv[1]
parser = configparser.RawConfigParser()
parser.optionxform = str
parser.read(path, encoding="utf-8")

removed = []
for section in list(parser.sections()):
    if parser.get(section, "type", fallback="") != "customcommand":
        continue
    if "metromenu" in parser.get(section, "command", fallback=""):
        parser.remove_section(section)
        removed.append(section)

for panel in [s for s in parser.sections() if s.startswith("panel")]:
    if parser.has_option(panel, "plugins"):
        names = [
            p.strip()
            for p in parser.get(panel, "plugins").split(",")
            if p.strip() and p.strip() not in removed
        ]
        parser.set(panel, "plugins", ", ".join(names))

if removed:
    with open(path, "w", encoding="utf-8") as handle:
        parser.write(handle)
        handle.write("\n")
    print("Removed LXQt panel widget(s): " + ", ".join(removed))
PY
}

remove_lxqt_hotkeys() {
    local conf="${XDG_CONFIG_HOME:-$HOME/.config}/lxqt/globalkeyshortcuts.conf"
    [[ -f "$conf" ]] || return 0
    python3 - "$conf" "$BIN" <<'PY' || true
import configparser
import sys

path, command = sys.argv[1], sys.argv[2]
parser = configparser.RawConfigParser()
parser.optionxform = str
parser.read(path, encoding="utf-8")

removed = [
    section
    for section in list(parser.sections())
    if parser.has_option(section, "command") and command in parser.get(section, "command")
]
for section in removed:
    parser.remove_section(section)

if removed:
    with open(path, "w", encoding="utf-8") as handle:
        parser.write(handle)
        handle.write("\n")
    print("Removed LXQt shortcut(s): " + ", ".join(removed))
PY
}

if [[ "$WANT_PANEL" == "1" ]]; then
    remove_panel_button
    remove_lxqt_panel_button
fi
if [[ "$WANT_HOTKEY" == "1" ]]; then
    remove_hotkeys
    remove_lxqt_hotkeys
fi

rm -rf "$APP_DIR"
rm -f "$BIN"
rm -f "$SHARE/applications/metromenu.desktop"
for size in 16 22 24 32 48 64 128 256; do
    rm -f "$SHARE/icons/hicolor/${size}x${size}/apps/metromenu.png"
done
rm -f "$SHARE/icons/hicolor/scalable/apps/metromenu.svg"

# Native panel plugin module + descriptor.
find "$HOME/.local" -path "*/xfce4/panel/plugins/libmetromenu.so" -delete 2>/dev/null || true
rm -f "$HOME/.local/share/xfce4/panel/plugins/metromenu.desktop"

# Startup caches (application list + rendered icons).
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/metromenu"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$SHARE/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "$SHARE/icons/hicolor" >/dev/null 2>&1 || true

if [[ "$WANT_PURGE" == "1" ]]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/metromenu"
    echo "Removed saved layout."
fi

echo "Uninstalled."
