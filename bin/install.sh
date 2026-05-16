#!/bin/sh
set -eu

PROJECT="porchlight"
SRC_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROOT="${STAGE_ROOT:-}"

prefix_path() {
  printf '%s%s\n' "$ROOT" "$1"
}

install_file() {
  src="$1"
  dest="$2"
  mode="$3"
  install -d -m 0755 "$(dirname "$(prefix_path "$dest")")"
  install -m "$mode" "$src" "$(prefix_path "$dest")"
}

install_dir() {
  install -d -m "$2" "$(prefix_path "$1")"
}

install_dir "/opt/$PROJECT/current/bin" 0755
install_dir "/opt/$PROJECT/current/systemd" 0755
install_dir "/etc/$PROJECT" 0755
install_dir "/var/lib/$PROJECT/www" 0755
install_dir "/var/lib/muster/home-assistant-mqtt-bridge" 0755

install_file "$SRC_ROOT/src/porchlight-ha-mqtt-bridge" "/opt/$PROJECT/current/bin/porchlight-ha-mqtt-bridge" 0755
install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.service" "/opt/$PROJECT/current/systemd/porchlight-ha-mqtt-bridge.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.timer" "/opt/$PROJECT/current/systemd/porchlight-ha-mqtt-bridge.timer" 0644
install_file "$SRC_ROOT/README.md" "/opt/$PROJECT/current/README.md" 0644
install_file "$SRC_ROOT/muster.yaml" "/opt/$PROJECT/current/muster.yaml" 0644
install_file "$SRC_ROOT/VERSION" "/opt/$PROJECT/current/VERSION" 0644

if [ ! -f "$(prefix_path "/etc/$PROJECT/porchlight.mqtt.env")" ]; then
  install_file "$SRC_ROOT/etc/porchlight.mqtt.env.example" "/etc/$PROJECT/porchlight.mqtt.env" 0600
fi

if [ ! -f "$(prefix_path "/etc/$PROJECT/enabled")" ]; then
  printf '%s\n' "true" > "$(prefix_path "/etc/$PROJECT/enabled")"
  chmod 0644 "$(prefix_path "/etc/$PROJECT/enabled")"
fi

if [ -z "$ROOT" ]; then
  install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.service" "/etc/systemd/system/porchlight-ha-mqtt-bridge.service" 0644
  install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.timer" "/etc/systemd/system/porchlight-ha-mqtt-bridge.timer" 0644
  systemctl daemon-reload
  systemctl enable --now porchlight-ha-mqtt-bridge.timer
fi
