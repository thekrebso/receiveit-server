#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

HCICONFIG=${HCICONFIG:-hciconfig}
HCITOOL=${HCITOOL:-hcitool}

# Disable LE advertising at the controller level
if command -v "$HCICONFIG" >/dev/null 2>&1; then
  $HCICONFIG hci0 noleadv >/dev/null 2>&1 || true
fi

if command -v "$HCITOOL" >/dev/null 2>&1; then
  # LE Set Advertise Enable = 0x00
  $HCITOOL -i hci0 cmd 0x08 0x000A 00 >/dev/null 2>&1 || true
fi

exit 0
