#!/bin/sh
set -eu

PROJECT="porchlight"
ROOT="${MUSTER_ROOT:-${STAGE_ROOT:-}}"
PURGE=0

if [ "${1:-}" = "--purge" ]; then
  PURGE=1
fi

prefix_path() {
  printf '%s%s\n' "$ROOT" "$1"
}

if [ -z "$ROOT" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now porchlight-discover.timer porchlight-scan.timer porchlight-deep-scan.timer porchlight-render.timer porchlight-health.timer porchlight-ha-mqtt-bridge.timer porchlight-ai-analysis.timer porchlight-setup-apply.path porchlight-setup-ap.service porchlight-web.service || true
  systemctl stop porchlight-scan.service porchlight-discover.service porchlight-deep-scan.service porchlight-render.service porchlight-health.service porchlight-ha-mqtt-bridge.service porchlight-ai-analysis.service porchlight-setup-apply.service porchlight-web.service || true
  rm -f /etc/systemd/system/porchlight-*.service
  rm -f /etc/systemd/system/porchlight-*.timer
  rm -f /etc/systemd/system/porchlight-*.path
  systemctl daemon-reload
else
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-ha-mqtt-bridge.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-ha-mqtt-bridge.timer")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-ai-analysis.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-ai-analysis.timer")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-scan.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-scan.timer")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-discover.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-discover.timer")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-deep-scan.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-deep-scan.timer")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-render.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-render.timer")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-health.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-health.timer")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-web.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-setup-ap.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-setup-apply.service")"
  rm -f "$(prefix_path "/etc/systemd/system/porchlight-setup-apply.path")"
fi

rm -f "$(prefix_path "/opt/$PROJECT/current")"
rm -rf "$(prefix_path "/opt/$PROJECT/releases")"

if [ "$PURGE" = "1" ]; then
  rm -rf "$(prefix_path "/etc/$PROJECT")"
  rm -rf "$(prefix_path "/var/lib/$PROJECT")"
  rm -rf "$(prefix_path "/var/lib/muster/home-assistant-mqtt-bridge")"
fi
