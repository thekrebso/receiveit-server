#!/bin/bash

set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

# Autoconnect helper: reacts to P2P events from systemd journal and falls back
# to polling peers. Triggers WPS-PBC connect on GO-NEG-REQUEST.

LOG=/tmp/p2p-autoconnect.log
IFACE=p2p-dev-wlan0
WPA_UNIT=p2p-wpa.service
SCAN_SERVICE=p2p-find.service
POLL_INTERVAL=3
DEBOUNCE_SECONDS=10

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] [p2p-autoconnect] $*" | tee -a "$LOG"; }

touch "$LOG"

debounce_dir=/tmp/p2p-debounce
mkdir -p "$debounce_dir"

debounce() {
    local key="$1" ttl="$2"
    local file="$debounce_dir/${key//:/-}"
    if [ -f "$file" ]; then
        local now=$(date +%s)
        local then=$(cat "$file" 2>/dev/null || echo 0)
        if [ $((now - then)) -lt "$ttl" ]; then
            return 1
        fi
    fi
    date +%s > "$file"
    return 0
}

connect_pbc() {
    local mac="$1"
    log "GO-NEG-REQUEST from $mac -> stopping scanner and running p2p_connect pbc"
    systemctl stop "$SCAN_SERVICE" >/dev/null 2>&1 || true
    if wpa_cli -i "$IFACE" p2p_connect "$mac" pbc go_intent=15 >/dev/null 2>&1; then
        log "p2p_connect issued for $mac"
    else
        log "p2p_connect failed for $mac"
    fi
}

resume_scanner_if_idle() {
    # Resume scanner if no p2p-wlan0* interface exists
    if ! ip -o link show | awk -F': ' '{print $2}' | grep -q '^p2p-wlan0'; then
        systemctl start "$SCAN_SERVICE" >/dev/null 2>&1 || true
    fi
}

# 1) Event-driven path via systemd journal
event_listener() {
    log "Listening to $WPA_UNIT logs for P2P events"
    journalctl -u "$WPA_UNIT" -f -n 0 | while read -r line; do
        # Extract MAC if present
        mac=$(echo "$line" | grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}') || true
        if echo "$line" | grep -q 'P2P-GO-NEG-REQUEST' && [ -n "${mac:-}" ]; then
            if debounce "go-neg-$mac" "$DEBOUNCE_SECONDS"; then
                connect_pbc "$mac"
            fi
            continue
        fi
        if echo "$line" | grep -q 'P2P-GROUP-REMOVED'; then
            log "Group removed detected in journal; resuming discovery"
            resume_scanner_if_idle
            continue
        fi
    done
}

# 2) Fallback polling path: check peers and attempt connect if possible
polling_loop() {
    log "Starting polling loop on $IFACE (interval=${POLL_INTERVAL}s, debounce=${DEBOUNCE_SECONDS}s)"
    while true; do
        peers=$(wpa_cli -i "$IFACE" p2p_peers 2>/dev/null || true)
        for peer in $peers; do
            info=$(wpa_cli -i "$IFACE" p2p_peer "$peer" 2>/dev/null || true)
            [ -z "$info" ] && continue
            # Prefer explicit dev_passwd_id=4 if present; otherwise, try to act on repeated PROV-DISC by attempting connect after debounce
            if echo "$info" | grep -q 'dev_passwd_id=4'; then
                if debounce "peer-$peer" "$DEBOUNCE_SECONDS"; then
                    connect_pbc "$peer"
                fi
            fi
        done
        resume_scanner_if_idle
        sleep "$POLL_INTERVAL"
    done
}

# Run both in parallel for robustness
event_listener &
polling_loop
