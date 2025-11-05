#!/bin/bash
FIND_INTERVAL=30

while true; do
	echo "[p2p-find] Running p2p_find on wlan0"
	sudo wpa_cli -i wlan0 p2p_find >/dev/null 2>&1
	sleep $FIND_INTERVAL
done
