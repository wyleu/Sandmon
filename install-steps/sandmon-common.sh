#!/bin/bash
# sandmon-common.sh
# Shared helpers for Sandmon ensure steps (aligned with sandbells-common.sh)
# - Settings path /etc/sandmon/settings.json
# - show_header, pause, log, need_cmd, service helpers
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/sandmon-common.sh"

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SETTINGS="${SANDBON_SETTINGS:-/etc/sandmon/settings.json}"

DEFAULT_TIME_HOSTS=(
    sandmon.local
    10.42.0.1
)

load_hotspot_settings() {
    HOTSPOT_SSID="Sandbells"
    HOTSPOT_PSK=""
    HOTSPOT_CHANNEL="6"
    HOTSPOT_IFACE="wlan0"
    HOTSPOT_CON="Sandbells"
    if [ -f "$SETTINGS" ] && command -v jq >/dev/null 2>&1; then
        HOTSPOT_SSID=$(jq -r '.ssid // .hotspot.ssid // "Sandbells"' "$SETTINGS" 2>/dev/null)
        HOTSPOT_PSK=$(jq -r '.psk // .hotspot.psk // empty' "$SETTINGS" 2>/dev/null)
        HOTSPOT_CHANNEL=$(jq -r '.channel // .hotspot.channel // 6' "$SETTINGS" 2>/dev/null)
        HOTSPOT_IFACE=$(jq -r '.ap_interface // .hotspot.interface // "wlan0"' "$SETTINGS" 2>/dev/null)
        HOTSPOT_CON=$(jq -r '.ap_connection // .hotspot.connection // "Sandbells"' "$SETTINGS" 2>/dev/null)
    fi
}

load_time_hosts() {
    TIME_HOSTS=()
    if [ -f "$SETTINGS" ] && command -v jq >/dev/null 2>&1; then
        mapfile -t TIME_HOSTS < <(jq -r '.time_hosts[]? // empty' "$SETTINGS" 2>/dev/null)
    fi
    if [ "${#TIME_HOSTS[@]}" -eq 0 ]; then
        TIME_HOSTS=("${DEFAULT_TIME_HOSTS[@]}")
    fi
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
show_header() {
    clear
    ELAPSED=$(( $(date +%s) - ${START_TIME:-$(date +%s)} ))
    CURRENT_HOSTNAME=$(hostname)
    GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "No git")
    GIT_BRANCH=$(git branch --show-current 2>/dev/null || echo "Not in git repo")
    PROJECT_DIR="${PROJECT_DIR:-/home/sandbells/Code/Sandmon}"

    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    WHITE='\033[1;37m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    NC='\033[0m'

    echo -e "${CYAN}======================================================================${NC}"
    echo -e " ${BOLD}${GREEN}Sandmon Tower Infrastructure Ensure${NC}"
    echo -e "${CYAN}======================================================================${NC}"
    echo -e " ${CYAN}Date${NC} : ${WHITE}$(date)${NC}"
    echo -e " ${CYAN}Elapsed Time${NC} : ${WHITE}${ELAPSED} seconds${NC}"
    echo -e " ${CYAN}User${NC} : ${WHITE}$(whoami)${NC}"
    echo -e " ${CYAN}Hostname${NC} : ${YELLOW}$CURRENT_HOSTNAME${NC}"
    echo -e " ${CYAN}URL${NC} : ${YELLOW}$CURRENT_HOSTNAME.local${NC}"
    echo -e " ${CYAN}Git Commit${NC} : ${WHITE}$GIT_HASH${NC}"
    echo -e " ${CYAN}Git Branch${NC} : ${WHITE}$GIT_BRANCH${NC}"
    echo -e " ${CYAN}Project Path${NC} : ${WHITE}$PROJECT_DIR${NC}"
    echo -e " ${CYAN}Machine${NC} : ${WHITE}$(cat /proc/cpuinfo | grep -m1 Model | cut -d: -f2 | xargs 2>/dev/null || echo Unknown)${NC}"
    echo -e " ${CYAN}Architecture${NC} : ${WHITE}$(uname -m) ($(getconf LONG_BIT)-bit)${NC}"

    MEM_TOTAL=$(free -h | awk '/^Mem:/ {print $2}')
    MEM_USED=$(free -h | awk '/^Mem:/ {print $3}')
    MEM_FREE=$(free -h | awk '/^Mem:/ {print $4}')
    MEM_PERCENT_USED=$(free | awk '/^Mem:/ {printf "%.0f", $3/$2 * 100}')
    echo -e " ${CYAN}Memory${NC} : ${WHITE}${MEM_USED} used of ${MEM_TOTAL} total${NC}"
    echo -e " ${WHITE}(${MEM_FREE} still free — ${MEM_PERCENT_USED}% in use)${NC}"

    TEMP=$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2 || echo "N/A")
    echo -e " ${CYAN}Temperature${NC} : ${WHITE}$TEMP${NC}"

    # Time (stratum-1 style on sandmon)
    STRATUM=$(chronyc tracking 2>/dev/null | grep -i stratum | awk '{print $3}' || echo "Unknown")
    RAW_SOURCE=$(chronyc sources 2>/dev/null | awk '/^\*/ {print $2; exit}')
    [ -z "$RAW_SOURCE" ] && RAW_SOURCE=$(chronyc sources 2>/dev/null | awk '/^#\*/ {print $2; exit}')
    TIMESERVER="${RAW_SOURCE:-local}"
    echo -e " ${CYAN}Time Source${NC} : ${WHITE}$TIMESERVER${NC}"
    if [ "$STRATUM" = "Unknown" ] || [ "$STRATUM" -gt 10 ] 2>/dev/null; then
        echo -e " ${CYAN}Clock Stratum${NC} : ${RED}$STRATUM (Not Locked!)${NC}"
    else
        echo -e " ${CYAN}Clock Stratum${NC} : ${WHITE}$STRATUM${NC}"
    fi

    # Facilities
    SSH_STATUS=$( [ "$(systemctl is-active ssh 2>/dev/null)" = "active" ] && echo -e "${GREEN}active${NC}" || echo -e "${RED}down${NC}" )
    GPSD_STATUS=$( [ "$(systemctl is-active my-gpsd 2>/dev/null)" = "active" ] && echo -e "${GREEN}active${NC}" || echo -e "${RED}down${NC}" )
    CHRONY_STATUS=$( [ "$(systemctl is-active chrony 2>/dev/null)" = "active" ] && echo -e "${GREEN}active${NC}" || echo -e "${RED}down${NC}" )
    HOTSPOT_EN=$(systemctl is-enabled sandmon-hotspot 2>/dev/null || echo "n/a")
    AP_SSID=$(iw dev wlan0 info 2>/dev/null | awk '/ssid/ {print $2; exit}')
    AP_TYPE=$(iw dev wlan0 info 2>/dev/null | awk '/type/ {print $2; exit}')

    echo -e " ${CYAN}SSH${NC} : ${SSH_STATUS}"
    echo -e " ${CYAN}my-gpsd${NC} : ${GPSD_STATUS}"
    echo -e " ${CYAN}chrony${NC} : ${CHRONY_STATUS}"
    echo -e " ${CYAN}hotspot unit${NC} : ${WHITE}$HOTSPOT_EN${NC}"
    echo -e " ${CYAN}WiFi/AP${NC} : ${WHITE}${AP_SSID:-—} (${AP_TYPE:-—})${NC}"

    if [ -n "$DISPLAY" ]; then
        DISPLAY_INFO="${XDG_SESSION_TYPE:-tty} [${DISPLAY}]"
    else
        DISPLAY_INFO="${XDG_SESSION_TYPE:-tty}"
    fi
    echo -e " ${CYAN}Display Server${NC} : ${WHITE}$DISPLAY_INFO${NC}"
    echo -e "${CYAN}======================================================================${NC}"
    echo ""
}

# ---------------------------------------------------------------------------
# Interactive helper
# ---------------------------------------------------------------------------
pause() {
    if [ "${QUICK_MODE:-false}" = true ]; then
        sleep 1.5
        return
    fi
    echo ""
    read -p "Press Enter to continue (or Q to stop) > " choice
    if [[ "$choice" =~ ^[Qq]$ ]]; then
        echo "Setup stopped safely."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log() {
    local tag="${LOGTAG:-sandmon}"
    logger -t "$tag" "$*" 2>/dev/null || true
    echo "$*"
}

# ---------------------------------------------------------------------------
# Privilege / environment checks
# ---------------------------------------------------------------------------
need_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "ERROR: this step must be run as root (or with sudo)"
        exit 1
    fi
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: required command '$1' not found"
        return 1
    }
}

# ---------------------------------------------------------------------------
# Package / service helpers
# ---------------------------------------------------------------------------
package_installed() {
    dpkg -s "$1" &>/dev/null
}

service_exists() {
    systemctl list-unit-files --type=service 2>/dev/null | grep -q "^$1"
}

service_is_active() {
    [ "$(systemctl is-active "$1" 2>/dev/null)" = "active" ]
}

service_is_enabled() {
    [ "$(systemctl is-enabled "$1" 2>/dev/null)" = "enabled" ]
}

stop_and_disable() {
    local unit="$1"
    if service_exists "$unit"; then
        sudo systemctl stop "$unit" 2>/dev/null || true
        sudo systemctl disable "$unit" 2>/dev/null || true
    fi
}

enable_and_start() {
    local unit="$1"
    if [ -f "/etc/systemd/system/$unit" ] || [ -f "/lib/systemd/system/$unit" ]; then
        sudo systemctl daemon-reload
        sudo systemctl enable "$unit"
        sudo systemctl restart "$unit" 2>/dev/null || sudo systemctl start "$unit"
    else
        echo "WARNING: unit $unit not found — skipping enable/start"
    fi
}
