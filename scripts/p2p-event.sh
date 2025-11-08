#!/bin/bash

# Robust P2P event handler invoked by wpa_cli (-a option).
# Typical invocation: script <iface> <event> [args]
# Some guides show only CONNECTED/DISCONNECTED, but many builds pass other
# events (e.g., P2P-*). We parse flexibly and log environment for clarity.

LOG_FILE=/tmp/p2p-events.log
STATE_FILE=/tmp/p2p-negotiating
GO_IP=192.168.49.1/24

timestamp() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
	echo "[$(timestamp)] [p2p-event] $*" | tee -a "$LOG_FILE"
}

dump_env() {
	env | grep -E '^(WPA_|INTERFACE=|IFACE=)' | sort | tee -a "$LOG_FILE" >/dev/null
}

# Parse args. Commonly $1=iface, $2=event.
IFACE="$1"; EVT="$2";
case "$IFACE" in
	wlan*|p2p-*|p2p-dev-*)
		EVENT="$EVT"; shift 2 || true ;;
	*)
		# Fall back to treating $1 as event if iface not present
		EVENT="$1"; shift 1 || true ;;
esac

log "ARGS: IFACE=${IFACE:-unknown} EVENT=${EVENT:-unknown} REM=$*"
if [ -n "$WPA_EVENT" ]; then
	log "ENV WPA_EVENT: $WPA_EVENT"
fi
dump_env

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
