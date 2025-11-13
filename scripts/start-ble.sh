#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

# Start a non-connectable BLE advertisement broadcasting a custom Service UUID
# and Service Data that includes the AP SSID from /etc/hostapd/hostapd.conf.

HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
SERVICE_UUID="139a34f3-f56a-46ea-ac7d-09bda997fa07"
BTCTL=${BTCTL:-bluetoothctl}

read_ssid() {
  local ssid
  ssid=$(grep -E '^ssid=' "$HOSTAPD_CONF" 2>/dev/null | head -n1 | cut -d'=' -f2- | tr -d '\r\n') || true
  if [ -z "${ssid:-}" ]; then
    ssid="ReceiveIt_001"
  fi
  printf '%s' "$ssid"
}

ascii_to_hex() {
  # Convert ASCII to lowercase hex without spaces
  # requires xxd
  printf '%s' "$1" | xxd -p -c 256 | tr 'A-F' 'a-f'
}

ensure_adapter_up() {
  rfkill unblock bluetooth 2>/dev/null || true
  $HCICONFIG hci0 up 2>/dev/null || true
}

advertise_with_bluetoothctl() {
  local ssid payload_hex
  ssid=$(read_ssid)
  payload_hex=$(ascii_to_hex "SSID=${ssid}")

  # Use bluetoothctl's advertise menu. This persists in bluetoothd until disabled.
  $BTCTL <<EOF >/dev/null
power on
system-alias ${ssid}
discoverable on
discoverable-timeout 0
menu advertise
type broadcast
tx-power on
local-name on
clear
uuids ${SERVICE_UUID}
service ${SERVICE_UUID} ${payload_hex}
back
advertise on
quit
EOF
}

main() {
  ensure_adapter_up

  if command -v "$BTCTL" >/dev/null 2>&1; then
    advertise_with_bluetoothctl && exit 0 || true
  fi

  echo "No suitable BLE tooling found (bluetoothctl). Install bluez." >&2
  exit 1
}

main "$@"
