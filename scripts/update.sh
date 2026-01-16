#!/bin/bash
set -e

DOMAIN="github.com"
MAX_ATTEMPTS=150  # ~5 minutes at 2s/attempt; adjust as needed
SLEEP_INTERVAL=2  # Seconds between attempts

# Function to wait for domain reachability
wait_for_domain() {
    local attempts=0
    echo "Waiting for $DOMAIN to be reachable..."
    while [ $attempts -lt $MAX_ATTEMPTS ]; do
        if ping -c 1 -W $SLEEP_INTERVAL "$DOMAIN" > /dev/null 2>&1; then
            echo "$DOMAIN is now reachable!"
            return 0
        fi
        echo "Attempt $((attempts + 1))/$MAX_ATTEMPTS: $DOMAIN not reachable yet (sleeping ${SLEEP_INTERVAL}s)..."
        sleep $SLEEP_INTERVAL
        ((attempts++))
    done
    echo "Error: Timed out waiting for $DOMAIN after $((attempts * SLEEP_INTERVAL)) seconds. Check your connection."
    return 1
}

cd /home/receiveit/receiveit-server || exit 1
./scripts/restore-wifi.sh

if wait_for_domain; then
    echo "Proceeding with update..."
    git pull
    ./scripts/update-files.sh

    # Ensure scripts are executable
    chmod +x ./scripts/start-ap.sh ./scripts/stop-ap.sh ./scripts/start-ble.sh ./scripts/stop-ble.sh || true

    # Enable AP and server
    systemctl daemon-reload
    systemctl enable receiveit-ap.service || true
    systemctl enable receiveit-server.service || true
    systemctl enable receiveit-ble.service || true
else
    echo "Skipping update due to network issues."
    exit 1
fi
