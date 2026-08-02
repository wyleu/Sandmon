#!/bin/bash
# 12-settings.sh — ensure /etc/sandmon/settings.json exists
# Args: $1 = QUICK_MODE (true/false)

QUICK_MODE=${1:-false}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=/dev/null
[ -f "$SCRIPT_DIR/sandmon-common.sh" ] && source "$SCRIPT_DIR/sandmon-common.sh"

if ! type pause &>/dev/null; then
  pause() { [ "$QUICK_MODE" = true ] && { sleep 1.5; return; }; read -p "Press Enter (Q=stop) > " c; [[ "$c" =~ ^[Qq]$ ]] && exit 1; }
fi

EXAMPLE="$REPO_DIR/settings.example.json"
DEST=/etc/sandmon/settings.json

echo "=================================================="
echo "Settings (/etc/sandmon/settings.json)"
echo "=================================================="

if [ ! -f "$EXAMPLE" ]; then
  echo "ERROR: missing $EXAMPLE"
  exit 1
fi

sudo mkdir -p /etc/sandmon
if [ -f "$DEST" ]; then
  echo "  already present: $DEST (left unchanged)"
else
  sudo cp "$EXAMPLE" "$DEST"
  sudo chmod 600 "$DEST"
  echo "  installed from example — edit psk before production"
fi
sudo ls -la "$DEST"
pause
