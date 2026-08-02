#!/bin/bash
# sandmon-status.sh — NETWORK / SERVER / HARDWARE / TIME (aligned with Sandbells)

set -euo pipefail

run() { timeout 3 "$@" 2>/dev/null || true; }

iface_state() {
  local f="/sys/class/net/$1/operstate"
  [ -r "$f" ] && cat "$f" || echo "missing"
}

iface_ipv4() {
  ip -4 -o addr show dev "$1" 2>/dev/null | awk '/inet / {print $4; exit}'
}

# single-line active|inactive|unknown
svc() {
  local s
  s=$(systemctl is-active "$1" 2>/dev/null | tr -d '\n' || true)
  case "$s" in
    active|inactive|failed|activating|deactivating) echo "$s" ;;
    *) echo "unknown" ;;
  esac
}

svc_enabled() {
  systemctl is-enabled "$1" 2>/dev/null | tr -d '\n' || echo "unknown"
}

HOSTNAME=$(hostname 2>/dev/null || echo unknown)
WIFI_STATE=$(iface_state wlan0)
WIRED_STATE=$(iface_state eth0)
WIFI_IP=$(iface_ipv4 wlan0)
WIRED_IP=$(iface_ipv4 eth0)

AP_SSID=$(iw dev wlan0 info 2>/dev/null | awk '/ssid/ {print $2; exit}')
AP_TYPE=$(iw dev wlan0 info 2>/dev/null | awk '/type/ {print $2; exit}')
AP_CHAN=$(iw dev wlan0 info 2>/dev/null | awk '/channel/ {print $2; exit}')

CLIENTS=0
if iw dev wlan0 station dump 2>/dev/null | grep -q '^Station'; then
  CLIENTS=$(iw dev wlan0 station dump 2>/dev/null | grep -c '^Station' || true)
fi
CLIENTS=${CLIENTS:-0}

TEMP=$(run vcgencmd measure_temp | sed "s/temp=//;s/'C/°C/")
FAN="—"
for p in /run/sandbells-fan.pct /tmp/sandbells-fan.pct /run/sandmon-fan.pct; do
  [ -r "$p" ] && { FAN="$(cat "$p")%"; break; }
done
MEM=$(run free -h | awk '/^Mem:/{print $3" / "$2}')
MODEL=$(tr -d '\0' </sys/firmware/devicetree/base/model 2>/dev/null || uname -m)
LOAD=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo "—")
THROTTLED="—"
out=$(run vcgencmd get_throttled)
if [ -n "$out" ]; then
  echo "$out" | grep -q '=0x0$' && THROTTLED=No || THROTTLED=Yes
fi

STRATUM=$(run chronyc tracking | awk -F': *' '/Stratum/ {print $2; exit}')
REF=$(run chronyc tracking | awk -F': *' '/Reference ID/ {print $2; exit}')
BEST=$(run chronyc sources | awk '/^\^\*/ {print $2; exit}')
[ -z "$BEST" ] && BEST=$(run chronyc sources | awk '/^#\*/ {print $2; exit}')
TIME_LABEL="${BEST:-NO LOCK}"
[ -n "$STRATUM" ] && TIME_LABEL="$TIME_LABEL  (stratum $STRATUM)"

GIT="—"
for repo in /home/sandbells/Code/Sandmon /home/sandbells/Code/Sandbells "$HOME/Code/Sandmon"; do
  if [ -d "$repo/.git" ]; then
    GIT="$(run git -C "$repo" branch --show-current) @ $(run git -C "$repo" rev-parse --short HEAD)"
    break
  fi
done

# gpsd: prefer active among common unit names
GPSD_SVC="gpsd"
for u in gpsd my-gpsd; do
  [ "$(svc "$u")" = "active" ] && { GPSD_SVC="$u"; break; }
done

HOTSPOT_EN=$(svc_enabled sandmon-hotspot)
HOTSPOT_AC=$(svc sandmon-hotspot)
# oneshot idle after success is normal
if [ "$HOTSPOT_EN" = "enabled" ] && [ "$HOTSPOT_AC" = "inactive" ]; then
  HOTSPOT_DISP="enabled(idle)"
else
  HOTSPOT_DISP="${HOTSPOT_EN}/${HOTSPOT_AC}"
fi

echo "============================================"
echo "  SANDBELLS  STATUS  (${HOSTNAME}.local)"
echo "============================================"
echo
echo "NETWORK"
printf "  WiFi/AP  : %-16s (%s)  type=%s  ch=%s\n" \
  "${AP_SSID:--}" "$WIFI_STATE" "${AP_TYPE:--}" "${AP_CHAN:--}"
printf "  AP IP    : %s   clients≈%s\n" "${WIFI_IP:--}" "$CLIENTS"
printf "  Wired    : %-16s          IP: %s\n" "$WIRED_STATE" "${WIRED_IP:--}"
echo
echo "SERVER"
echo "  Hostname : ${HOSTNAME}.local"
echo "  Git      : $GIT"
echo "  Services : hotspot=$HOTSPOT_DISP  ${GPSD_SVC}=$(svc "$GPSD_SVC")  chrony=$(svc chrony)"
echo
echo "HARDWARE"
echo "  Model    : $MODEL"
echo "  Temp/Fan : ${TEMP:--}  /  $FAN"
echo "  Memory   : ${MEM:--}"
echo "  Load     : $LOAD"
echo "  Throttled: $THROTTLED"
echo
echo "TIME"
echo "  Source   : $TIME_LABEL"
echo "  Ref      : ${REF:--}"
echo
echo "============================================"
