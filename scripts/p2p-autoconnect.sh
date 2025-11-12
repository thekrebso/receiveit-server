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

# After group formation, we may need to reopen WPS or tear down idle group.
GO_IFACE=""
WPS_ACTIVE=0
LAST_STA_TIME=0
# If set to 1, tear down GO as soon as last station disconnects to ensure new discovery works reliably
REMOVE_GO_ON_EMPTY=1
GROUP_IDLE_TIMEOUT=30  # fallback seconds before removal if not removing immediately

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

has_sta() {
    local gi="$1"
    local out
    out=$(wpa_cli -i "$gi" list_sta 2>/dev/null || true)
    echo "$out" | grep -Eqi '([0-9a-f]{2}:){5}[0-9a-f]{2}'
}

# 1) Event-driven path via systemd journal
event_listener() {
    log "Listening to $WPA_UNIT logs for P2P events"
    journalctl -u "$WPA_UNIT" -f -n 0 | while read -r line; do
        # Extract MAC if present
        mac=$(echo "$line" | grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}') || true

        # Track group lifecycle
        if echo "$line" | grep -q 'P2P-GROUP-STARTED'; then
            # Example: P2P-GROUP-STARTED p2p-wlan0-0 GO ssid="DIRECT-xy" freq=2412 go_dev_addr=xx
            GO_IFACE=$(echo "$line" | awk '{for (i=1;i<=NF;i++) if ($i ~ /^p2p-wlan0/) {print $i; break}}')
            WPS_ACTIVE=0
            log "Group started on $GO_IFACE"
            continue
        fi
        if echo "$line" | grep -q 'P2P-GROUP-REMOVED'; then
            log "Group removed detected; clearing state and resuming discovery"
            GO_IFACE=""
            WPS_ACTIVE=0
            resume_scanner_if_idle
            continue
        fi
        if echo "$line" | grep -q 'WPS-PBC-ACTIVE'; then
            WPS_ACTIVE=1
            log "WPS PBC active on $GO_IFACE"
            continue
        fi
        if echo "$line" | grep -q 'WPS-PBC-DISABLE'; then
            WPS_ACTIVE=0
            log "WPS PBC disabled on $GO_IFACE"
            continue
        fi

        # React to provisioning discovery requests
        if echo "$line" | grep -q 'P2P-PROV-DISC-PBC-REQ' && [ -n "${mac:-}" ]; then
            if [ -z "$GO_IFACE" ]; then
                if debounce "prov-disc-$mac" "$DEBOUNCE_SECONDS"; then
                    log "PROV-DISC-PBC-REQ from $mac while no group -> initiating connect"
                    connect_pbc "$mac"
                fi
            else
                # Already a GO
                if [ $REMOVE_GO_ON_EMPTY -eq 1 ] && ! has_sta "$GO_IFACE"; then
                    log "PROV-DISC received; GO exists but empty -> removing group $GO_IFACE to restart negotiation"
                    wpa_cli -i "$IFACE" p2p_group_remove "$GO_IFACE" >/dev/null 2>&1 || true
                    GO_IFACE=""
                    WPS_ACTIVE=0
                    resume_scanner_if_idle
                else
                    if [ $WPS_ACTIVE -eq 0 ]; then
                        if debounce "reopen-wps" 10; then
                            log "PROV-DISC received; reopening WPS PBC on $GO_IFACE"
                            wpa_cli -i "$GO_IFACE" wps_pbc >/dev/null 2>&1 || true
                        fi
                    fi
                fi
            fi
            continue
        fi

        if echo "$line" | grep -q 'P2P-GO-NEG-REQUEST' && [ -n "${mac:-}" ]; then
            if debounce "go-neg-$mac" "$DEBOUNCE_SECONDS"; then
                connect_pbc "$mac"
            fi
            continue
        fi

        if echo "$line" | grep -q 'AP-STA-CONNECTED'; then
            LAST_STA_TIME=$(date +%s)
            log "Station connected (mac=$mac)"
            continue
        fi
        if echo "$line" | grep -q 'AP-STA-DISCONNECTED'; then
            LAST_STA_TIME=$(date +%s)
            # Schedule idle check
            (
              sleep 5
              if [ -n "$GO_IFACE" ]; then
                  if ! has_sta "$GO_IFACE"; then
                      if [ $REMOVE_GO_ON_EMPTY -eq 1 ]; then
                          log "No stations remain on $GO_IFACE -> removing group immediately"
                          wpa_cli -i "$IFACE" p2p_group_remove "$GO_IFACE" >/dev/null 2>&1 || true
                          GO_IFACE=""
                          WPS_ACTIVE=0
                          resume_scanner_if_idle
                      else
                          now=$(date +%s)
                          if [ $((now - LAST_STA_TIME)) -ge $GROUP_IDLE_TIMEOUT ]; then
                              log "Group $GO_IFACE idle -> removing to restart discovery"
                              wpa_cli -i "$IFACE" p2p_group_remove "$GO_IFACE" >/dev/null 2>&1 || true
                              GO_IFACE=""
                              WPS_ACTIVE=0
                              resume_scanner_if_idle
                          else
                              # Reopen WPS PBC for re-association attempt
                              if [ $WPS_ACTIVE -eq 0 ]; then
                                  log "Group empty; reopening WPS PBC"
                                  wpa_cli -i "$GO_IFACE" wps_pbc >/dev/null 2>&1 || true
                              fi
                          fi
                      fi
                  fi
              fi
            ) &
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
