#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

# Start a non-connectable BLE advertisement broadcasting a custom Service UUID
# and Service Data that includes the AP SSID from /etc/hostapd/hostapd.conf.

HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
SERVICE_UUID="139a34f3-f56a-46ea-ac7d-09bda997fa07"
BTCTL=${BTCTL:-bluetoothctl}
HCICONFIG=${HCICONFIG:-hciconfig}
HCITOOL=${HCITOOL:-hcitool}
BTMGMT=${BTMGMT:-btmgmt}

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

advertise_with_btmgmt() {
  # Best-effort fallback using btmgmt; not all versions support service data easily.
  # Here we at least advertise the UUID and tx-power/name includes disabled.
  $BTMGMT -i hci0 power on >/dev/null 2>&1 || true
  $BTMGMT -i hci0 le on >/dev/null 2>&1 || true
  # Remove existing adv instances to avoid duplicates
  $BTMGMT -i hci0 rm-adv -a >/dev/null 2>&1 || true
  # Add non-connectable broadcast with Service UUID; btmgmt will auto-start it.
  $BTMGMT -i hci0 add-adv -t broadcast -u ${SERVICE_UUID} -c none >/dev/null 2>&1
}

advertise_with_hcitool_raw() {
  # Raw HCI fallback: minimal advertising with Flags + 128-bit Service UUID
  # Note: This does not include Service Data to keep complexity low in fallback
  # Build Advertising Data: [Len=2, Flags=0x01|0x04|0x06?] + [Len=17, Type=0x07, 128-bit UUID]
  # Use Flags: LE General Discoverable (0x02) + BR/EDR Not Supported (0x04) => 0x06

  local uuid_nodash uuid_le bytes ad len1 len2 total pad
  uuid_nodash=$(echo "$SERVICE_UUID" | tr -d '-')
  # Convert UUID to little-endian byte order for AD type 0x07
  # 128-bit UUID endian swap by fields: time_low(4), time_mid(2), time_hi(2), clock_seq(2), node(6)
  # Reverse each field's byte order, then append node as-is
  local tl tm th cs node
  tl=${uuid_nodash:0:8}
  tm=${uuid_nodash:8:4}
  th=${uuid_nodash:12:4}
  cs=${uuid_nodash:16:4}
  node=${uuid_nodash:20:12}
  # function to reverse hex in 2-char steps
  rev2() { echo "$1" | sed -E 's/../& /g' | awk '{ for(i=NF;i>=1;i--) printf "%s", $i }'; }
  uuid_le=$(rev2 "$tl")$(rev2 "$tm")$(rev2 "$th")$(rev2 "$cs")$node

  # Advertising payload: Flags (len=2: type 0x01, data 0x06) + 128-bit Service UUID list (len=17: type 0x07, 16 bytes UUID)
  ad="02 01 06 11 07 $(echo "$uuid_le" | sed -E 's/../& /g')"

  # Disable advertising, set params, set data, enable advertising
  $HCITOOL -i hci0 cmd 0x08 0x000A 00 >/dev/null 2>&1 || true
  # Set advertising parameters (intervals default 0x0800 ~1.28s, non-connectable undirected: adv type 0x03)
  $HCITOOL -i hci0 cmd 0x08 0x0006 00 08 00 08 03 00 00 00 00 00 00 00 00 07 00 >/dev/null 2>&1 || true

  # Set advertising data (max 31 bytes). Build from $ad
  # Convert to HCI payload: length (1 byte) + bytes (31 bytes padded with 0x00)
  bytes=$(echo "$ad" | tr -d ' ')
  len1=$(( ${#bytes} / 2 ))
  # Build padded data string of 31 bytes
  pad=$((31 - len1))
  total=$(for i in $(seq 1 $pad); do printf '00'; done; echo)
  $HCITOOL -i hci0 cmd 0x08 0x0008 $(printf "%02x" "$len1") $(echo "$ad") $(
    for i in $(seq 1 $pad); do printf '00 '; done
  ) >/dev/null 2>&1 || true

  # Enable advertising
  $HCITOOL -i hci0 cmd 0x08 0x000A 01 >/dev/null 2>&1 || true
}

main() {
  ensure_adapter_up

  if command -v "$BTCTL" >/dev/null 2>&1; then
    advertise_with_bluetoothctl && exit 0 || true
  fi

  if command -v "$BTMGMT" >/dev/null 2>&1; then
    advertise_with_btmgmt && exit 0 || true
  fi

  if command -v "$HCITOOL" >/dev/null 2>&1 && command -v "$HCICONFIG" >/dev/null 2>&1; then
    advertise_with_hcitool_raw && exit 0 || true
  fi

  echo "No suitable BLE tooling found (bluetoothctl/btmgmt/hcitool). Install bluez." >&2
  exit 1
}

main "$@"
