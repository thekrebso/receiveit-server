#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
SERVICE_UUID="139a34f3-f56a-46ea-ac7d-09bda997fa07"
HCICONFIG=${HCICONFIG:-hciconfig}
HCITOOL=${HCITOOL:-hcitool}

# Advertising mode: 'peripheral' (connectable) or 'broadcast' (non-connectable).
# Many scanner apps only list connectable devices; default to 'peripheral'.
ADV_TYPE=${ADV_TYPE:-peripheral}


read_ssid() {
  local ssid
  ssid=$(grep -E '^ssid=' "$HOSTAPD_CONF" 2>/dev/null | head -n1 | cut -d'=' -f2- | tr -d '\r\n') || true
  if [ -z "${ssid:-}" ]; then
    ssid="Pendrive_001"
  fi
  printf '%s' "$ssid"
}

ascii_to_hex() {
  # Convert ASCII to lowercase hex without spaces
  # requires xxd
  printf '%s' "$1" | xxd -p -c 256 | tr 'A-F' 'a-f'
}

# Convert a hex string (e.g. "414243") into space-separated bytes ("41 42 43")
hex_to_spaced_bytes() {
  local hex="$1"
  echo "$hex" | sed -E 's/../& /g' | sed 's/ $//'
}

# Convert canonical UUID to 128-bit little-endian bytes (space-separated)
uuid128_to_le_bytes() {
  local uuid="$1" hex
  hex=$(echo "$uuid" | tr 'A-F' 'a-f' | tr -d '-')
  echo "$hex" | sed -E 's/../& /g' | awk '{for(i=NF;i>0;i--) printf("%s%s", $i, (i>1?" ":""))}'
}

count_bytes() {
  local data="$1"
  if [ -z "$data" ]; then echo 0; else echo "$data" | awk '{print NF}'; fi
}

ensure_adapter_up() {
  rfkill unblock bluetooth 2>/dev/null || true
  $HCICONFIG hci0 up 2>/dev/null || true
}

advertise_with_hcitool() {
  # Raw HCI method for BLE advertising with 128-bit Service UUID and Service Data (SSID)
  ensure_adapter_up

  local ssid ssid_hex ssid_bytes uuid_le adv_flags adv_uuid_list adv_data adv_len
  local uuid_list_len sr_payload_bytes sr_payload_count max_payload sr_data sr_len

  ssid=$(read_ssid)
  # Encode SSID as bytes (no prefix) to maximize payload room
  ssid_hex=$(ascii_to_hex "${ssid}")
  ssid_bytes=$(hex_to_spaced_bytes "$ssid_hex")

  # Advertising Data structures (each includes its own length byte):
  # - Flags: 02 01 06
  adv_flags="02 01 06"

  # - Complete List of 128-bit UUIDs: length 0x11 (type + 16 bytes)
  uuid_le=$(uuid128_to_le_bytes "$SERVICE_UUID")
  uuid_list_len=$(printf "%02x" $((1 + 16)))
  adv_uuid_list="${uuid_list_len} 07 ${uuid_le}"
  adv_data="${adv_flags} ${adv_uuid_list}"
  adv_len=$(count_bytes "$adv_data")

  # Scan Response: Service Data - 128-bit (type 0x21)
  # Structure length byte covers (type + 16-byte UUID + payload)
  max_payload=13
  sr_payload_bytes=""
  sr_payload_count=0
  for b in $ssid_bytes; do
    if [ $sr_payload_count -ge $max_payload ]; then break; fi
    if [ -z "$sr_payload_bytes" ]; then sr_payload_bytes="$b"; else sr_payload_bytes="$sr_payload_bytes $b"; fi
    sr_payload_count=$((sr_payload_count+1))
  done
  local sr_len_field
  sr_len_field=$(printf "%02x" $((1 + 16 + sr_payload_count)))
  sr_data="${sr_len_field} 21 ${uuid_le} ${sr_payload_bytes}"
  sr_len=$(count_bytes "$sr_data")

  # Advertising type for parameters: 0x00 ADV_IND (connectable) or 0x03 ADV_NONCONN_IND
  local adv_type_param
  case "${ADV_TYPE}" in
    peripheral) adv_type_param="00" ;;
    broadcast) adv_type_param="03" ;;
    *) adv_type_param="00" ;;
  esac

  # Set advertising parameters: interval 100ms, public address, channels 37-39
  $HCITOOL -i hci0 cmd 0x08 0x0006 a0 00 a0 00 ${adv_type_param} 00 00 00 00 00 00 00 00 07 00 >/dev/null

  # Set Advertising Data
  local adv_len_hex
  adv_len_hex=$(printf "%02x" ${adv_len})
  $HCITOOL -i hci0 cmd 0x08 0x0008 ${adv_len_hex} ${adv_data} >/dev/null

  # Set Scan Response Data
  local sr_len_hex
  sr_len_hex=$(printf "%02x" ${sr_len})
  $HCITOOL -i hci0 cmd 0x08 0x0009 ${sr_len_hex} ${sr_data} >/dev/null

  # Enable advertising
  $HCITOOL -i hci0 cmd 0x08 0x000A 01 >/dev/null
}

main() {
  ensure_adapter_up

  if command -v "$HCITOOL" >/dev/null 2>&1; then
    advertise_with_hcitool && exit 0 || true
  fi

  echo "No suitable BLE tooling found (hcitool). Install bluez-tools." >&2
  exit 1
}

main "$@"
