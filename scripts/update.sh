#!/bin/bash
set -e

cd /home/receiveit/receiveit-server || exit 1
./scripts/restore-wifi.sh
sleep 3

git pull
./scripts/update-files.sh

# Ensure scripts are executable
chmod +x ./scripts/start-ap.sh ./scripts/stop-ap.sh ./scripts/start-ble.sh ./scripts/stop-ble.sh || true

# Enable AP and server
systemctl daemon-reload
systemctl enable receiveit-ap.service || true
systemctl enable receiveit-server.service || true
systemctl enable receiveit-ble.service || true
