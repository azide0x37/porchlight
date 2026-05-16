#!/bin/sh
set -eu

PROJECT="porchlight"
ROOT="${STAGE_ROOT:-}"
PURGE=0

if [ "${1:-}" = "--purge" ]; then
  PURGE=1
fi

prefix_path() {
  printf '%s%s\n' "$ROOT" "$1"
}

if [ -z "$ROOT" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now porchlight-ha-mqtt-bridge.timer || true
  systemctl stop porchlight-ha-mqtt-bridge.service || true
  rm -f /etc/systemd/system/porchlight-ha-mqtt-bridge.service
  rm -f /etc/systemd/system/porchlight-ha-mqtt-bridge.timer
  systemctl daemon-reload
else
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-ha-mqtt-bridge.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-ha-mqtt-bridge.timer")"
fi

rm -f "$(prefix_path "/opt/$PROJECT/current")"
rm -rf "$(prefix_path "/opt/$PROJECT/releases")"

if [ "$PURGE" = "1" ]; then
  rm -rf "$(prefix_path "/etc/$PROJECT")"
  rm -rf "$(prefix_path "/var/lib/$PROJECT")"
  rm -rf "$(prefix_path "/var/lib/muster/home-assistant-mqtt-bridge")"
fi
