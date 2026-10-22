#!/bin/bash
# sandmon-hotspot-ensure.sh — one AP only: SSID from settings.json
set -euo pipefail

SETTINGS="${SANDBON_SETTINGS:-/etc/sandmon/settings.json}"
LOGTAG="sandmon-hotspot"

log() { logger -t "$LOGTAG" "$*" 2>/dev/null || true; echo "$*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: need $1"; exit 1; }; }
need_cmd nmcli
need_cmd jq
need_cmd iw

if [ ! -f "$SETTINGS" ]; then
  log "ERROR: missing $SETTINGS"
  exit 1
fi

SSID=$(jq -r '.ssid // "Sandbells"' "$SETTINGS")
PSK=$(jq -r '.psk // empty' "$SETTINGS")
CHANNEL=$(jq -r '.channel // 6' "$SETTINGS")
CON=$(jq -r '.ap_connection // "Sandbells"' "$SETTINGS")
IFACE=$(jq -r '.ap_interface // "wlan0"' "$SETTINGS")

if [ -z "$PSK" ] || [ "${#PSK}" -lt 8 ]; then
  log "ERROR: psk missing or shorter than 8 chars in $SETTINGS"
  exit 1
fi

while IFS= read -r name; do
  [ -z "$name" ] && continue
  [ "$name" = "$CON" ] && continue
  log "deleting extra profile: $name"
  nmcli connection delete "$name" 2>/dev/null || true
done < <(nmcli -t -f NAME,TYPE connection show | awk -F: '$2=="802-11-wireless" || $2=="wifi" {print $1}' | grep -E '^Sandbells' || true)

if ! nmcli -t -f NAME connection show | grep -qx "$CON"; then
  log "creating connection $CON"
  nmcli connection add type wifi ifname "$IFACE" con-name "$CON" ssid "$SSID" autoconnect yes
fi

log "configuring $CON (ssid=$SSID channel=$CHANNEL)"
nmcli connection modify "$CON" \
  802-11-wireless.mode ap \
  802-11-wireless.ssid "$SSID" \
  802-11-wireless.band bg \
  802-11-wireless.channel "$CHANNEL" \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.proto "wpa rsn" \
  wifi-sec.pairwise "tkip ccmp" \
  wifi-sec.group tkip \
  wifi-sec.pmf disable \
  wifi-sec.psk "$PSK" \
  ipv4.method shared \
  ipv6.method ignore \
  connection.interface-name "$IFACE" \
  connection.autoconnect yes

nmcli connection up "$CON"
sleep 2

CUR_SSID=$(iw dev "$IFACE" info 2>/dev/null | awk '/ssid/ {print $2; exit}')
CUR_TYPE=$(iw dev "$IFACE" info 2>/dev/null | awk '/type/ {print $2; exit}')
ADDR=$(ip -4 -br addr show "$IFACE" 2>/dev/null | awk '{print $3}')

log "ssid=$CUR_SSID type=$CUR_TYPE addr=$ADDR"

if [ "$CUR_TYPE" != "AP" ] || [ "$CUR_SSID" != "$SSID" ]; then
  log "ERROR: expected AP ssid=$SSID, got type=$CUR_TYPE ssid=$CUR_SSID"
  exit 1
fi

log "OK: hotspot $SSID on $IFACE ($ADDR)"
