#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

BTCTL=${BTCTL:-bluetoothctl}
HCITOOL=${HCITOOL:-hcitool}
BTMGMT=${BTMGMT:-btmgmt}

# Try to stop advertising via bluetoothctl
if command -v "$BTCTL" >/dev/null 2>&1; then
  $BTCTL <<EOF >/dev/null 2>&1 || true
menu advertise
advertise off
back
quit
EOF
fi

# Try to stop raw advertising
if command -v "$HCITOOL" >/dev/null 2>&1; then
  $HCITOOL -i hci0 cmd 0x08 0x000A 00 >/dev/null 2>&1 || true
fi

# Try to remove btmgmt adverts
if command -v "$BTMGMT" >/dev/null 2>&1; then
  $BTMGMT -i hci0 rm-adv -a >/dev/null 2>&1 || true
fi

exit 0
