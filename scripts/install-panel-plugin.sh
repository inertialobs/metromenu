#!/usr/bin/env bash
# Build and install the native Xfce panel plugin for the start menu.
#
# Usage:  ./scripts/install-panel-plugin.sh [--add]
#   --add    also insert the plugin into panel 1 (leftmost) and restart it
#
# The plugin is installed user-locally, so no root is needed:
#   module     -> ~/.local/lib/<multiarch>/xfce4/panel/plugins/libmetromenu.so
#   descriptor -> ~/.local/share/xfce4/panel/plugins/metromenu.desktop
#
# Building requires the development headers:
#   sudo apt install libgtk-3-dev libxfce4panel-2.0-dev
set -euo pipefail

# The native plugin is built against libxfce4panel and only loads in the Xfce
# panel.  LXQt has a different plugin ABI (ILxQtPanelPlugin/Qt) and ships a
# ready-made "Custom Command" widget, so point the user there instead.
_lxqt_env="${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_DESKTOP:-}:${DESKTOP_SESSION:-}"
if [[ "$_lxqt_env" == *[Ll][Xx][Qq][Tt]* ]] \
    || { command -v lxqt-panel >/dev/null 2>&1 && ! command -v xfce4-panel >/dev/null 2>&1; }; then
    echo "error: this plugin is Xfce only; it cannot be loaded by the LXQt panel." >&2
    echo "On LXQt add the start menu as a 'Custom Command' panel widget instead:" >&2
    echo "    scripts/integrate-panel.sh" >&2
    exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_SRC="$SRC/panel-plugin/metromenu-plugin.c"
DESCRIPTOR="$SRC/panel-plugin/metromenu.desktop"
MODULE_NAME="metromenu"
MODULE="lib${MODULE_NAME}.so"

WANT_ADD=0
for arg in "$@"; do
    case "$arg" in
        --add) WANT_ADD=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# --- locate the panel headers/libraries -----------------------------------
# libxfce4panel-2.0.pc has a private dep on libxfce4ui-2.pc which is not
# always installed, so build the flags by hand instead of using it directly.
XFCE_INCDIR="$(pkg-config --variable=includedir libxfce4panel-2.0)"
XFCE_LIBDIR="$(pkg-config --variable=libdir libxfce4panel-2.0)"
BASE_CFLAGS="$(pkg-config --cflags gtk+-3.0 gmodule-2.0 glib-2.0 libxfce4util-1.0)"
BASE_LIBS="$(pkg-config --libs gtk+-3.0 gmodule-2.0 glib-2.0 libxfce4util-1.0)"

if [[ ! -f "$XFCE_INCDIR/xfce4/libxfce4panel-2.0/libxfce4panel/libxfce4panel.h" ]]; then
    echo "error: libxfce4panel-2.0 headers not found - install libxfce4panel-2.0-dev" >&2
    exit 1
fi

# --- build ----------------------------------------------------------------
BUILD_DIR="$SRC/panel-plugin/build"
mkdir -p "$BUILD_DIR"
echo "Compiling $MODULE ..."
gcc -shared -fPIC -O2 -Wall -Wextra \
    -I"$XFCE_INCDIR/xfce4/libxfce4panel-2.0" \
    $BASE_CFLAGS \
    -o "$BUILD_DIR/$MODULE" \
    "$PLUGIN_SRC" \
    -L"$XFCE_LIBDIR" -lxfce4panel-2.0 $BASE_LIBS

# Sanity check: the register symbol must be exported.
if ! nm -D --defined-only "$BUILD_DIR/$MODULE" | grep -q xfce_panel_module_construct; then
    echo "error: $MODULE does not export xfce_panel_module_construct" >&2
    exit 1
fi

# --- install (user-local) -------------------------------------------------
case "$XFCE_LIBDIR" in
    /usr*) USER_LIBDIR="$HOME/.local${XFCE_LIBDIR#/usr}/xfce4/panel/plugins" ;;
    *)     USER_LIBDIR="$HOME/.local/lib/xfce4/panel/plugins" ;;
esac
USER_DATADIR="$HOME/.local/share/xfce4/panel/plugins"

mkdir -p "$USER_LIBDIR" "$USER_DATADIR"
cp "$BUILD_DIR/$MODULE" "$USER_LIBDIR/$MODULE"
cp "$DESCRIPTOR" "$USER_DATADIR/$MODULE_NAME.desktop"

echo "  module     : $USER_LIBDIR/$MODULE"
echo "  descriptor : $USER_DATADIR/$MODULE_NAME.desktop"

# --- optionally add to a panel --------------------------------------------
if [[ "$WANT_ADD" == "1" ]]; then
    if ! command -v xfconf-query >/dev/null 2>&1; then
        echo "error: xfconf-query not found" >&2
        exit 1
    fi
    PANEL=1
    max_id=0
    while IFS= read -r line; do
        id="${line#/plugins/plugin-}"
        [[ "$id" =~ ^[0-9]+$ ]] || continue
        (( id > max_id )) && max_id=$id
    done < <(xfconf-query -c xfce4-panel -p /plugins -l 2>/dev/null || true)
    new_id=$((max_id + 1))

    xfconf-query -c xfce4-panel -p "/plugins/plugin-$new_id" -n -t string -s "$MODULE_NAME"

    mapfile -t ids < <(xfconf-query -c xfce4-panel -p "/panels/panel-$PANEL/plugin-ids" -v 2>/dev/null | grep -E '^[0-9]+$' || true)
    args=()
    for value in "$new_id" "${ids[@]}"; do
        args+=(-t int -s "$value")
    done
    xfconf-query -c xfce4-panel -p "/panels/panel-$PANEL/plugin-ids" "${args[@]}"

    xfce4-panel --restart >/dev/null 2>&1 || true
    echo "Added plugin-$new_id to panel $PANEL (leftmost)."
else
    echo
    echo "Now restart the panel and add it from 'Add New Items', or run:"
    echo "  $SRC/scripts/install-panel-plugin.sh --add"
fi
