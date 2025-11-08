#!/bin/bash

# Autoconnect helper: listens to wpa_cli event log and triggers WPS-PBC
# on P2P-GO-NEG-REQUEST events. Useful when wpa_cli -a doesn't invoke
# action scripts for P2P events on this platform.

LOG=/tmp/p2p-autoconnect.log
WPA_LOG=/run/p2p-wpa_cli.log
IFACE=p2p-dev-wlan0

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] [p2p-autoconnect] $*" | tee -a "$LOG"; }

touch "$LOG"

# Start a background wpa_cli logger if not already present
if ! pgrep -f "wpa_cli -i $IFACE -f $WPA_LOG" >/dev/null 2>&1; then
    log "Starting wpa_cli background logger to $WPA_LOG"
    /usr/sbin/wpa_cli -i "$IFACE" -f "$WPA_LOG" -B || log "Failed to start wpa_cli logger"
fi

touch "$WPA_LOG"

# Simple debounce map using temp files in /tmp
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

log "Tailing $WPA_LOG for P2P-GO-NEG-REQUEST events"
tail -n0 -F "$WPA_LOG" | while read -r line; do
    mac="$(echo "$line" | grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}')"
    if echo "$line" | grep -q "P2P-GO-NEG-REQUEST" && [ -n "$mac" ]; then
        if debounce "neg-$mac" 5; then
            log "Detected GO-NEG-REQUEST from $mac -> initiating WPS-PBC"
            /usr/sbin/wpa_cli -i "$IFACE" p2p_connect "$mac" pbc go_intent=15 >/dev/null 2>&1 \
                && log "p2p_connect issued for $mac" \
                || log "p2p_connect failed for $mac"
        fi
    fi
done
