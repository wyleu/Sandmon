# Sandmon

Tower infrastructure: WiFi AP (SSID Sandbells), GPS/PPS time (chrony stratum 1), optional LCD clock.

## Facilities (settings.json)

Config: /etc/sandmon/settings.json (see settings.example.json).

- Hotspot: sandmon-hotspot-ensure.sh, sandmon-hotspot.service
- GPS: my-gpsd.service
- Status: sandmon-status.sh (NETWORK / SERVER / HARDWARE / TIME)

Helpers ensure/repair declared state; safe to re-run.

## Quick install on a box

    sudo mkdir -p /etc/sandmon
    sudo cp settings.example.json /etc/sandmon/settings.json
    sudo chmod 600 /etc/sandmon/settings.json
    # edit psk etc.

    sudo install -m 755 install-steps/sandmon-hotspot-ensure.sh /usr/local/sbin/
    sudo install -m 755 install-steps/sandmon-status.sh /usr/local/sbin/
    sudo install -m 644 systemd/sandmon-hotspot.service /etc/systemd/system/
    sudo install -m 644 systemd/my-gpsd.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now my-gpsd.service
    sudo systemctl enable sandmon-hotspot.service
    sudo systemctl start sandmon-hotspot.service
    sandmon-status.sh

Kiosks join SSID from settings and use sandmon.local or 10.42.0.1 for time.
