#!/usr/bin/env bash
# Add a start-menu button to the session's panel (Xfce or LXQt).
#
# Usage:  ./scripts/integrate-panel.sh [PANEL_NUMBER]
#
#   Xfce: creates a "launcher" panel plugin whose single item runs the
#         metromenu command, inserted as the first panel item.
#   LXQt: adds a "Custom Command" widget to ~/.config/lxqt/panel.conf (the
#         running panel reloads on its own), placed at the far left.
set -euo pipefail

PANEL="${1:-1}"
BIN="${HOME}/.local/bin/metromenu"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -x "$BIN" ]]; then
    echo "error: $BIN not found - run scripts/install.sh first" >&2
    exit 1
fi

# The python package lives in the installed tree; fall back to the source tree.
if [[ -d "${HOME}/.local/share/metromenu/metromenu" ]]; then
    PYROOT="${HOME}/.local/share/metromenu"
else
    PYROOT="$SRC"
fi

detect_lxqt() {
    local env="${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_DESKTOP:-}:${DESKTOP_SESSION:-}"
    if [[ "$env" == *[Ll][Xx][Qq][Tt]* ]]; then
        return 0
    fi
    if command -v lxqt-panel >/dev/null 2>&1 && ! command -v xfce4-panel >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

if detect_lxqt; then
    PYTHONPATH="$PYROOT${PYTHONPATH:+:$PYTHONPATH}" python3 - "$PANEL" "$BIN" <<'PY'
import sys

from metromenu import actions

panel = int(sys.argv[1])
command = sys.argv[2]
ok = actions.add_command_to_lxqt_panel(
    command, icon="metromenu", text="", name="metromenu", panel=panel
)
sys.exit(0 if ok else 1)
PY
    echo "Added the start menu as an LXQt 'Custom Command' widget (panel $PANEL)."
    echo "The panel reloads automatically; if the button does not appear, add it"
    echo "manually via the panel's 'Add Widgets' dialog (Custom Command -> $BIN)."
    echo "Remove it with: scripts/uninstall.sh --panel"
    exit 0
fi

# --- Xfce -----------------------------------------------------------------
PANEL_DIR="${HOME}/.config/xfce4/panel"
CHANNEL="xfce4-panel"

if ! command -v xfconf-query >/dev/null 2>&1; then
    echo "error: xfconf-query not found (is this an Xfce session?)" >&2
    exit 1
fi

# Find the next free plugin id.
max_id=0
while IFS= read -r line; do
    id="${line#/plugins/plugin-}"
    [[ "$id" =~ ^[0-9]+$ ]] || continue
    (( id > max_id )) && max_id=$id
done < <(xfconf-query -c "$CHANNEL" -p /plugins -l 2>/dev/null || true)
new_id=$((max_id + 1))

# Create the launcher item inside launcher-<plugin-id>/.
launcher_dir="$PANEL_DIR/launcher-$new_id"
mkdir -p "$launcher_dir"
item="metromenu-$(date +%s)-$$.desktop"
cat > "$launcher_dir/$item" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=开始菜单
Name[en]=Start Menu
Comment=Windows 10 风格开始菜单
Exec=$BIN
Icon=metromenu
Terminal=false
StartupNotify=false
Categories=Utility;X-XFCE;
EOF

# Register the plugin and its item.
xfconf-query -c "$CHANNEL" -p "/plugins/plugin-$new_id" -n -t string -s launcher
xfconf-query -c "$CHANNEL" -p "/plugins/plugin-$new_id/items" -n -t string -s "$item"

# Prepend the new plugin id to the panel's plugin list.
mapfile -t ids < <(xfconf-query -c "$CHANNEL" -p "/panels/panel-$PANEL/plugin-ids" -v 2>/dev/null | grep -E '^[0-9]+$' || true)
args=()
for value in "$new_id" "${ids[@]}"; do
    args+=(-t int -s "$value")
done
xfconf-query -c "$CHANNEL" -p "/panels/panel-$PANEL/plugin-ids" "${args[@]}"

# Bring the panel back with the new button.
xfce4-panel --restart >/dev/null 2>&1 || true

echo "Added start menu button as panel plugin-$new_id (panel $PANEL)."
echo "Remove it with: scripts/uninstall.sh --panel"
