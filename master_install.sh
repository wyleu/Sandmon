#!/bin/bash
# master_install.sh
# Sandmon master ensure/reconcile — orchestrates numbered install steps
# (Same shape as Sandbells master_install.sh; facilities via settings + ensure scripts)

START_TIME=$(date +%s)

# Configuration (defaults; settings.json is authoritative where used)
TIME_SERVER="sandmon.local"

# Shared helpers if present (header, pause, etc.)
# Prefer a local common file; fall back to name used on kiosks if you copy one over
if [ -f ./install-steps/sandmon-common.sh ]; then
    # shellcheck source=/dev/null
    source ./install-steps/sandmon-common.sh
elif [ -f ./install-steps/sandbells-common.sh ]; then
    # shellcheck source=/dev/null
    source ./install-steps/sandbells-common.sh
fi

if type show_header &>/dev/null; then
    show_header 2>/dev/null || true
fi

sudo -v

# Ensure /etc/sandmon/settings.json exists early
if [ ! -f /etc/sandmon/settings.json ]; then
    echo "==> Creating /etc/sandmon/settings.json from example"
    sudo install -d /etc/sandmon
    if [ -f settings.example.json ]; then
        sudo cp settings.example.json /etc/sandmon/settings.json
    elif [ -f install-steps/settings.example.json ]; then
        sudo cp install-steps/settings.example.json /etc/sandmon/settings.json
    else
        echo "ERROR: no settings.example.json found"
        exit 1
    fi
    sudo chmod 600 /etc/sandmon/settings.json
    echo "    Edit /etc/sandmon/settings.json — set real hotspot psk etc."
fi

QUICK_MODE=false
if [[ "${1:-}" == "--quick" || "${1:-}" == "-q" ]]; then
    QUICK_MODE=true
    echo "Quick mode activated!"
fi

echo "Starting Sandmon ensure steps..."
echo "Hotspot / GPS / status reconcile (numbered scripts in install-steps/)"
echo ""

STEPS_DIR="./install-steps"
chmod +x "$STEPS_DIR"/[0-9][0-9]-*.sh 2>/dev/null || true

for step in $STEPS_DIR/[0-9][0-9]-*.sh; do
    if [ -x "$step" ]; then
        if type show_header &>/dev/null; then
            show_header
        fi
        echo "Running: $step"
        echo "----------------------------------------------------------------------"
        "$step" "$QUICK_MODE"
        EXIT_CODE=$?
        if [ $EXIT_CODE -ne 0 ]; then
            echo "Step cancelled or failed (exit code $EXIT_CODE)"
            exit 1
        fi
        echo "----------------------------------------------------------------------"
        echo ""
    fi
done

ELAPSED=$(( $(date +%s) - START_TIME ))
echo "======================================================================"
echo "ALL STEPS COMPLETED in ${ELAPSED} seconds"
echo ""
echo "Check:  sandmon-status.sh"
echo "Hotspot ensure:  sudo systemctl start sandmon-hotspot.service"
echo ""
echo "Optional:  sudo reboot"
echo "======================================================================"
