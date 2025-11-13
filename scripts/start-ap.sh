#!/bin/bash
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin

HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
DNSMASQ_CONF="/etc/dnsmasq.d/receiveit-ap.conf"
HOSTAPD_PID="/run/hostapd-receiveit.pid"
DNSMASQ_PID="/run/dnsmasq-receiveit.pid"
AP_IP_CIDR="192.168.49.1/24"

# Stop conflicting services
systemctl stop NetworkManager.service >/dev/null 2>&1 || true
systemctl stop wpa_supplicant.service >/dev/null 2>&1 || true
systemctl stop dnsmasq.service >/dev/null 2>&1 || true

# Prepare wlan0 with static IP
ip link set wlan0 down || true
ip addr flush dev wlan0 || true
ip link set wlan0 up
ip addr add "$AP_IP_CIDR" dev wlan0 || true

# Start hostapd (daemonize with PID file)
if [ -f "$HOSTAPD_PID" ] && kill -0 "$(cat "$HOSTAPD_PID" 2>/dev/null || echo 0)" 2>/dev/null; then
  kill "$(cat "$HOSTAPD_PID")" || true
  rm -f "$HOSTAPD_PID"
fi
hostapd -B -P "$HOSTAPD_PID" "$HOSTAPD_CONF"

# Start dnsmasq (scoped to wlan0 with PID file)
if [ -f "$DNSMASQ_PID" ] && kill -0 "$(cat "$DNSMASQ_PID" 2>/dev/null || echo 0)" 2>/dev/null; then
  kill "$(cat "$DNSMASQ_PID")" || true
  rm -f "$DNSMASQ_PID"
fi
dnsmasq --conf-file="$DNSMASQ_CONF" --pid-file="$DNSMASQ_PID"
