#!/bin/sh
set -eu

PROJECT="porchlight"
CONFIG_DIR="${CONFIG_DIR:-/etc/$PROJECT}"
SETUP_ENV="$CONFIG_DIR/setup.env"

if [ -f "$CONFIG_DIR/setup-complete" ]; then
  exit 0
fi

if [ -f "$SETUP_ENV" ]; then
  # shellcheck disable=SC1090
  . "$SETUP_ENV"
fi

if [ "${PORCHLIGHT_APPLIANCE_MODE:-0}" != "1" ]; then
  exit 0
fi

if ! command -v nmcli >/dev/null 2>&1; then
  printf '%s\n' "nmcli is required for Porchlight setup AP" >&2
  exit 0
fi

WIFI_IFACE="${PORCHLIGHT_SETUP_WIFI_IFACE:-wlan0}"
SSID="${PORCHLIGHT_SETUP_SSID:-Porchlight-setup}"
PASSWORD="${PORCHLIGHT_SETUP_PASSWORD:-porchlight20}"

if nmcli -t -f DEVICE,TYPE,STATE dev status | grep -q "^[^:]*:wifi:connected$"; then
  exit 0
fi

if nmcli -t -f NAME connection show --active | grep -qx "$SSID"; then
  exit 0
fi

nmcli radio wifi on || true
nmcli device wifi hotspot ifname "$WIFI_IFACE" ssid "$SSID" password "$PASSWORD"
