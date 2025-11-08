#!/bin/bash

# Robust P2P event handler invoked by wpa_cli (-a option).
# Receives: <event> [args]
# Logs events, auto-accepts P2P GO negotiation via WPS Push Button, assigns IP.

LOG_FILE=/tmp/p2p-events.log
STATE_FILE=/tmp/p2p-negotiating
GO_IP=192.168.49.1/24

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
	echo "[$(timestamp)] [p2p-event] $*" | tee -a "$LOG_FILE"
}

EVENT="$1"
shift || true

log "RAW: EVENT=$EVENT ARGS=$*"

# Auto-start WPS PBC when a negotiation request arrives
if [ "$EVENT" = "P2P-GO-NEG-REQUEST" ]; then
	peer_mac="$1"
	if [ -z "$peer_mac" ]; then
		log "GO-NEG-REQUEST with missing peer MAC"
		exit 0
	fi
	if [ -f "$STATE_FILE" ]; then
		log "Already negotiating; ignoring duplicate GO-NEG-REQUEST from $peer_mac"
		exit 0
	fi
	log "Starting WPS-PBC GO negotiation with $peer_mac"
	touch "$STATE_FILE"
	/usr/sbin/wpa_cli -i p2p-dev-wlan0 p2p_connect "$peer_mac" pbc go_intent=15 >/dev/null 2>&1 &
	exit 0
fi

# When group starts, bring interface up and assign IP early
if [ "$EVENT" = "P2P-GROUP-STARTED" ]; then
	GROUP_IFACE=""
	for arg in "$@"; do
		case "$arg" in
			p2p-*) GROUP_IFACE="$arg"; break;;
		esac
	done
	if [ -n "$GROUP_IFACE" ]; then
		log "Group started on interface $GROUP_IFACE"
		ip link set "$GROUP_IFACE" up 2>/dev/null || log "Failed to set link up for $GROUP_IFACE"
		if ! ip -4 addr show "$GROUP_IFACE" | grep -q "${GO_IP%/*}"; then
			ip addr add "$GO_IP" dev "$GROUP_IFACE" 2>/dev/null && log "Assigned $GO_IP to $GROUP_IFACE" || log "Failed to assign $GO_IP to $GROUP_IFACE"
		else
			log "IP already present on $GROUP_IFACE"
		fi
	else
		log "P2P-GROUP-STARTED but no p2p-* interface token detected in args: $*"
	fi
	rm -f "$STATE_FILE"
	exit 0
fi

# Clean state when group removed
if [ "$EVENT" = "P2P-GROUP-REMOVED" ]; then
	log "Group removed; clearing state"
	rm -f "$STATE_FILE"
	exit 0
fi

exit 0
