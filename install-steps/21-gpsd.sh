#!/bin/bash
# 21-gpsd.sh — my-gpsd under systemd (GPS + PPS)
# Args: $1 = QUICK_MODE (true/false)

QUICK_MODE=${1:-false}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=/dev/null
[ -f "$SCRIPT_DIR/sandmon-common.sh" ] && source "$SCRIPT_DIR/sandmon-common.sh"

if ! type pause &>/dev/null; then
  pause() { [ "$QUICK_MODE" = true ] && { sleep 1.5; return; }; read -p "Press Enter (Q=stop) > " c; [[ "$c" =~ ^[Qq]$ ]] && exit 1; }
fi

UNIT_SRC="$REPO_DIR/systemd/my-gpsd.service"
UNIT_DST=/etc/systemd/system/my-gpsd.service

echo "=================================================="
echo "GPS (my-gpsd)"
echo "=================================================="

[ -f "$UNIT_SRC" ] || { echo "ERROR: missing $UNIT_SRC"; exit 1; }

sudo install -m 644 "$UNIT_SRC" "$UNIT_DST"
echo "  installed $UNIT_DST"

sudo systemctl daemon-reload
sudo systemctl enable my-gpsd.service
sudo systemctl restart my-gpsd.service

echo ""
systemctl is-active my-gpsd || true
systemctl is-enabled my-gpsd || true
echo "GPS step completed"
pause
