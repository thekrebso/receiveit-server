#!/bin/bash

set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

# Autoconnect helper (polling): periodically inspects P2P peers and initiates
# WPS Push Button connection (p2p_connect ... pbc) when a peer advertises
# dev_passwd_id=4 (WPS PBC) and GO negotiation has not yet been attempted.
# Avoids reliance on wpa_cli action events which are limited on this build.

LOG=/tmp/p2p-autoconnect.log
IFACE=p2p-dev-wlan0
SCAN_SERVICE=p2p-find.service
POLL_INTERVAL=2
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

log "Starting polling loop on $IFACE (interval=${POLL_INTERVAL}s, debounce=${DEBOUNCE_SECONDS}s)"

while true; do
    # List peers known to wpa_supplicant
    peers=$(wpa_cli -i "$IFACE" p2p_peers 2>/dev/null || true)
    if [ -z "$peers" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    for peer in $peers; do
        # Fetch detailed info
        info=$(wpa_cli -i "$IFACE" p2p_peer "$peer" 2>/dev/null || true)
        [ -z "$info" ] && continue

        # Detect WPS PBC push button intent
        if echo "$info" | grep -q 'dev_passwd_id=4'; then
            if debounce "peer-$peer" "$DEBOUNCE_SECONDS"; then
                log "Peer $peer advertising WPS PBC (dev_passwd_id=4); initiating GO negotiation"
                # Pause background scanning to reduce LISTEN/SCAN collisions
                systemctl stop "$SCAN_SERVICE" >/dev/null 2>&1 || true
                if wpa_cli -i "$IFACE" p2p_connect "$peer" pbc go_intent=15 >/dev/null 2>&1; then
                    log "p2p_connect issued for $peer"
                else
                    log "p2p_connect failed for $peer"
                fi
            fi
        fi
    done

    # Resume scanner if no group exists
    if ! ip -o link show | awk -F': ' '{print $2}' | grep -q '^p2p-wlan0'; then
        systemctl start "$SCAN_SERVICE" >/dev/null 2>&1 || true
    fi

    sleep "$POLL_INTERVAL"
done
