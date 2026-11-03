#!/usr/bin/env bash
# Bind a keyboard shortcut that toggles the start menu.
#
# Usage:  ./scripts/menu-hotkey.sh [KEY]
#   KEY defaults to "<Super>" (the Windows key).
#   Examples: "<Super>", "<Super>s", "<Primary>space"
#
#   Xfce: writes the shortcut into xfconf (xfce4-keyboard-shortcuts).
#   LXQt: writes a command shortcut into ~/.config/lxqt/globalkeyshortcuts.conf.
set -euo pipefail

KEY="${1:-<Super>}"
CMD="${HOME}/.local/bin/metromenu"

if [[ ! -x "$CMD" ]]; then
    echo "error: $CMD not found - run scripts/install.sh first" >&2
    exit 1
fi

detect_lxqt() {
    local env="${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_DESKTOP:-}:${DESKTOP_SESSION:-}"
    if [[ "$env" == *[Ll][Xx][Qq][Tt]* ]]; then return 0; fi
    if command -v lxqt-globalkeysd >/dev/null 2>&1 && ! command -v xfconf-query >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

if detect_lxqt; then
    # GTK accelerator -> LXQt/Qt accelerator ("Control%2BAlt%2BT" style).
    SHORTCUT="$(python3 - "$KEY" <<'PY'
import sys

mods = {
    "super": "Meta", "meta": "Meta",
    "primary": "Control", "control": "Control", "ctrl": "Control",
    "alt": "Alt", "mod1": "Alt",
    "shift": "Shift",
}
aliases = {
    "space": "Space", "return": "Return", "enter": "Return",
    "escape": "Escape", "tab": "Tab", "backspace": "Backspace",
    "print": "Print",
}

text = sys.argv[1]
parts: list[str] = []
key = ""
i = 0
while i < len(text):
    if text[i] == "<":
        end = text.find(">", i)
        if end == -1:
            key += text[i]
            i += 1
            continue
        name = text[i + 1:end]
        parts.append(mods.get(name.lower(), name))
        i = end + 1
    else:
        key += text[i]
        i += 1
key = key.strip()
key = aliases.get(key.lower(), key.upper() if len(key) == 1 else key)
combo = parts + ([key] if key else [])
print("+".join(combo).replace("+", "%2B"))
PY
)"

    CONF="${XDG_CONFIG_HOME:-$HOME/.config}/lxqt/globalkeyshortcuts.conf"
    mkdir -p "$(dirname "$CONF")"
    [[ -f "$CONF" ]] || printf '[General]\n' > "$CONF"

    python3 - "$CONF" "$SHORTCUT" "$CMD" <<'PY'
import configparser
import sys

path, shortcut, command = sys.argv[1], sys.argv[2], sys.argv[3]

parser = configparser.RawConfigParser()
parser.optionxform = str
parser.read(path, encoding="utf-8")
if not parser.has_section("General"):
    parser.add_section("General")

# Drop an earlier entry on the same key (this is an idempotent re-bind).
for section in list(parser.sections()):
    if section.split(".", 1)[0] == shortcut:
        parser.remove_section(section)

# Find a free "<shortcut>.<id>" suffix.
ids: list[int] = []
for section in parser.sections():
    if "." in section:
        try:
            ids.append(int(section.rsplit(".", 1)[1]))
        except ValueError:
            pass
section = f"{shortcut}.{(max(ids) + 1) if ids else 1}"
parser.add_section(section)
parser.set(section, "Comment", "Start menu")
parser.set(section, "Enabled", "true")
parser.set(section, "command", command)
parser.set(section, "arguments", "")

with open(path, "w", encoding="utf-8") as handle:
    parser.write(handle)
    handle.write("\n")
PY

    echo "Bound '$KEY' to the start menu in $CONF."
    echo "Log out and back in (or run lxqt-config-globalkeyshortcuts) if it does"
    echo "not take effect immediately."
    exit 0
fi

# --- Xfce -----------------------------------------------------------------
CHANNEL="xfce4-keyboard-shortcuts"
PROP="/commands/custom/$KEY"

if xfconf-query -c "$CHANNEL" -p "$PROP" -n -t string -s "$CMD" 2>/dev/null; then
    :
else
    xfconf-query -c "$CHANNEL" -p "$PROP" -t string -s "$CMD"
fi

echo "Bound '$KEY' to the start menu."
echo "If '$KEY' does not respond, make sure it is not already used by"
echo "xfwm4 or the whisker menu in Settings -> Keyboard -> Application Shortcuts."
