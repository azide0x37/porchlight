#!/bin/sh
set -eu

PROJECT="porchlight"
CONFIG_DIR="${CONFIG_DIR:-/etc/$PROJECT}"
STATE_DIR="${PORCHLIGHT_STATE_DIR:-/run/$PROJECT}"
ACTION_FILE="$STATE_DIR/setup-action"

[ -f "$ACTION_FILE" ] || exit 0
ACTION=$(sed -n '1p' "$ACTION_FILE" | tr -d '[:space:]')
rm -f "$ACTION_FILE"

case "$ACTION" in
  restart_bridge)
    systemctl start porchlight-ha-mqtt-bridge.service
    ;;
  shutdown_setup_ap)
    if [ -f "$CONFIG_DIR/setup.env" ]; then
      # shellcheck disable=SC1090
      . "$CONFIG_DIR/setup.env"
    fi
    SSID="${PORCHLIGHT_SETUP_SSID:-Porchlight-setup}"
    if command -v nmcli >/dev/null 2>&1; then
      nmcli connection down "$SSID" >/dev/null 2>&1 || true
    fi
    systemctl stop porchlight-setup-ap.service >/dev/null 2>&1 || true
    systemctl disable porchlight-setup-ap.service >/dev/null 2>&1 || true
    ;;
  *)
    printf '%s\n' "rejected setup action: $ACTION" >&2
    exit 1
    ;;
esac
