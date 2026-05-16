#!/bin/sh
set -eu

PROJECT="porchlight"
SRC_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROOT="${STAGE_ROOT:-}"
VERSION=$(tr -d '[:space:]' < "$SRC_ROOT/VERSION")
RELEASE_DIR="/opt/$PROJECT/releases/$VERSION"
CURRENT_LINK="/opt/$PROJECT/current"

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

install_dir "$RELEASE_DIR/bin" 0755
install_dir "$RELEASE_DIR/systemd" 0755
install_dir "/etc/$PROJECT" 0755
install_dir "/var/lib/$PROJECT/www" 0755
install_dir "/var/lib/muster/home-assistant-mqtt-bridge" 0755

install_file "$SRC_ROOT/src/porchlight-ha-mqtt-bridge" "$RELEASE_DIR/bin/porchlight-ha-mqtt-bridge" 0755
install_file "$SRC_ROOT/bin/doctor.sh" "$RELEASE_DIR/bin/doctor.sh" 0755
install_file "$SRC_ROOT/bin/update.sh" "$RELEASE_DIR/bin/update.sh" 0755
install_file "$SRC_ROOT/bin/uninstall.sh" "$RELEASE_DIR/bin/uninstall.sh" 0755
install_file "$SRC_ROOT/bin/render-units.sh" "$RELEASE_DIR/bin/render-units.sh" 0755
install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.service" "$RELEASE_DIR/systemd/porchlight-ha-mqtt-bridge.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.timer" "$RELEASE_DIR/systemd/porchlight-ha-mqtt-bridge.timer" 0644
install_file "$SRC_ROOT/README.md" "$RELEASE_DIR/README.md" 0644
install_file "$SRC_ROOT/MUSTER.md" "$RELEASE_DIR/MUSTER.md" 0644
install_file "$SRC_ROOT/SECURITY.md" "$RELEASE_DIR/SECURITY.md" 0644
install_file "$SRC_ROOT/RELEASE.md" "$RELEASE_DIR/RELEASE.md" 0644
install_file "$SRC_ROOT/muster.yaml" "$RELEASE_DIR/muster.yaml" 0644
install_file "$SRC_ROOT/VERSION" "$RELEASE_DIR/VERSION" 0644

if [ -n "$ROOT" ]; then
  ln -sfn "$(prefix_path "$RELEASE_DIR")" "$(prefix_path "$CURRENT_LINK")"
else
  ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
fi

if [ ! -f "$(prefix_path "/etc/$PROJECT/porchlight.mqtt.env")" ]; then
  install_file "$SRC_ROOT/etc/porchlight.mqtt.env.example" "/etc/$PROJECT/porchlight.mqtt.env" 0600
fi

if [ ! -f "$(prefix_path "/etc/$PROJECT/porchlight.env")" ]; then
  install_file "$SRC_ROOT/etc/porchlight.env.example" "/etc/$PROJECT/porchlight.env" 0644
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
