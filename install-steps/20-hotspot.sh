#!/bin/bash
# 20-hotspot.sh — install hotspot ensure helper + unit, reconcile once
# Args: $1 = QUICK_MODE (true/false)

QUICK_MODE=${1:-false}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=/dev/null
[ -f "$SCRIPT_DIR/sandmon-common.sh" ] && source "$SCRIPT_DIR/sandmon-common.sh"

if ! type pause &>/dev/null; then
  pause() { [ "$QUICK_MODE" = true ] && { sleep 1.5; return; }; read -p "Press Enter (Q=stop) > " c; [[ "$c" =~ ^[Qq]$ ]] && exit 1; }
fi

HELPER_SRC="$SCRIPT_DIR/sandmon-hotspot-ensure.sh"
UNIT_SRC="$REPO_DIR/systemd/sandmon-hotspot.service"
HELPER_DST=/usr/local/sbin/sandmon-hotspot-ensure.sh
UNIT_DST=/etc/systemd/system/sandmon-hotspot.service

echo "=================================================="
echo "Hotspot ensure (SSID from settings.json)"
echo "=================================================="

for f in "$HELPER_SRC" "$UNIT_SRC"; do
  [ -f "$f" ] || { echo "ERROR: missing $f"; exit 1; }
done

sudo install -m 755 "$HELPER_SRC" "$HELPER_DST"
echo "  installed $HELPER_DST"
sudo install -m 644 "$UNIT_SRC" "$UNIT_DST"
echo "  installed $UNIT_DST"

sudo systemctl daemon-reload
sudo systemctl enable sandmon-hotspot.service
sudo systemctl start sandmon-hotspot.service

echo ""
systemctl is-enabled sandmon-hotspot.service || true
echo "Hotspot step completed"
pause
