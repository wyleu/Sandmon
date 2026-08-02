#!/bin/bash
# 22-status.sh — install sandmon-status.sh (NETWORK/SERVER/HARDWARE/TIME)
# Args: $1 = QUICK_MODE (true/false)

QUICK_MODE=${1:-false}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
[ -f "$SCRIPT_DIR/sandmon-common.sh" ] && source "$SCRIPT_DIR/sandmon-common.sh"

if ! type pause &>/dev/null; then
  pause() { [ "$QUICK_MODE" = true ] && { sleep 1.5; return; }; read -p "Press Enter (Q=stop) > " c; [[ "$c" =~ ^[Qq]$ ]] && exit 1; }
fi

SRC="$SCRIPT_DIR/sandmon-status.sh"
DST=/usr/local/sbin/sandmon-status.sh

echo "=================================================="
echo "Status helper"
echo "=================================================="

[ -f "$SRC" ] || { echo "ERROR: missing $SRC"; exit 1; }

sudo install -m 755 "$SRC" "$DST"
echo "  installed $DST"
echo "  run: sandmon-status.sh"
pause
