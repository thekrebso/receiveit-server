#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

HOSTAPD_PID="/run/hostapd-receiveit.pid"
DNSMASQ_PID="/run/dnsmasq-receiveit.pid"

# Stop dnsmasq
if [ -f "$DNSMASQ_PID" ]; then
  PID="$(cat "$DNSMASQ_PID" 2>/dev/null || echo)"
  [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
  rm -f "$DNSMASQ_PID"
else
  pkill -f "dnsmasq .*receiveit-ap.conf" >/dev/null 2>&1 || true
fi

# Stop hostapd
if [ -f "$HOSTAPD_PID" ]; then
  PID="$(cat "$HOSTAPD_PID" 2>/dev/null || echo)"
  [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
  rm -f "$HOSTAPD_PID"
else
  pkill -x hostapd >/dev/null 2>&1 || true
fi

# Leave wlan0 up with IP for any local services
ip link set wlan0 up 2>/dev/null || true
