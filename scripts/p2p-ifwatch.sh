#!/bin/bash

IP_ADDR="192.168.49.1/24"

while true; do
	for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -E '^p2p-'); do
		# Bring interface up
		ip link set "$iface" up 2>/dev/null

		# Assign IP if not already
		if ! ip -4 addr show "$iface" | grep -q "${IP_ADDR%/*}"; then
			echo "[p2p-ifwatch] Configuring $iface with $IP_ADDR"
			ip addr add "$IP_ADDR" dev "$iface" 2>/dev/null
		fi
	done
	sleep 2
done
