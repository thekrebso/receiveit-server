#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

BTCTL=${BTCTL:-bluetoothctl}

# Try to stop advertising via bluetoothctl
if command -v "$BTCTL" >/dev/null 2>&1; then
  $BTCTL <<EOF >/dev/null 2>&1 || true
menu advertise
advertise off
back
quit
EOF
fi

exit 0
