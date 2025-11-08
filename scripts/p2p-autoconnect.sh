#!/bin/bash

PATH=/usr/sbin:/usr/bin:/sbin:/bin

# Autoconnect helper: subscribes to wpa_cli event stream and triggers WPS-PBC
# on P2P-GO-NEG-REQUEST events. This avoids unsupported flags and works with
# wpa_cli v2.10 as shipped on Raspberry Pi OS.

LOG=/tmp/p2p-autoconnect.log
IFACE=p2p-dev-wlan0

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] [p2p-autoconnect] $*" | tee -a "$LOG"; }

touch "$LOG"

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

log "Subscribing to wpa_cli events on $IFACE"

# -s short output (no timestamps). stdbuf to flush line-by-line.
stdbuf -oL /usr/sbin/wpa_cli -i "$IFACE" -p /var/run/wpa_supplicant -s | while read -r line; do
    mac="$(echo "$line" | grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}')"

    if echo "$line" | grep -q "P2P-GO-NEG-REQUEST" && [ -n "$mac" ]; then
        if debounce "neg-$mac" 5; then
            log "Detected GO-NEG-REQUEST from $mac -> initiating WPS-PBC"
            # Pause active scanning to avoid LISTEN/SCAN collisions during negotiation
            systemctl stop p2p-find.service >/dev/null 2>&1 || true
            /usr/sbin/wpa_cli -i "$IFACE" p2p_connect "$mac" pbc go_intent=15 >/dev/null 2>&1 \
                && log "p2p_connect issued for $mac" \
                || log "p2p_connect failed for $mac"
        fi
        continue
    fi

    if echo "$line" | grep -q "P2P-GROUP-STARTED"; then
        log "Group started ($line)"
        continue
    fi

    if echo "$line" | grep -q "P2P-GROUP-REMOVED"; then
        log "Group removed; resuming discovery"
        systemctl start p2p-find.service >/dev/null 2>&1 || true
        continue
    fi
done
