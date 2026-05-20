#!/bin/sh
set -eu

PROJECT="porchlight"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ROOT="${MUSTER_ROOT:-${STAGE_ROOT:-}}"
INSTALL_DIR="$ROOT/opt/$PROJECT"
CONFIG_DIR="$ROOT/etc/$PROJECT"
CONFIG_FILE="$CONFIG_DIR/$PROJECT.env"
MQTT_CONFIG_FILE="$CONFIG_DIR/$PROJECT.mqtt.env"
SYSTEMD_DIR="$ROOT/etc/systemd/system"
DEFAULT_MANIFEST_URL="https://github.com/azide0x37/porchlight/releases/latest/download/manifest.json"
TMP_DIR="${TMPDIR:-/tmp}/$PROJECT-install.$$"
VERSION=""
RELEASE_DIR=""
CURRENT_LINK="$INSTALL_DIR/current"
APPLIANCE_MODE=0

while [ "${1:-}" ]; do
  case "$1" in
    --appliance)
      APPLIANCE_MODE=1
      ;;
    *)
      printf '%s\n' "usage: install.sh [--appliance]" >&2
      exit 2
      ;;
  esac
  shift
done

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

prefix_path() {
  case "$1" in
    "$ROOT"/*) printf '%s\n' "$1" ;;
    *) printf '%s%s\n' "$ROOT" "$1" ;;
  esac
}

log() {
  printf '%s\n' "$*"
}

json_value() {
  key="$1"
  file="$2"
  sed -n "s/.*\"$key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$file" | head -n 1
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

fetch_file() {
  src="$1"
  dest="$2"
  case "$src" in
    http://*|https://*)
      if ! command -v curl >/dev/null 2>&1; then
        printf '%s\n' "curl is required to fetch $src" >&2
        exit 1
      fi
      curl -fsSL "$src" -o "$dest"
      ;;
    *)
      cp "$src" "$dest"
      ;;
  esac
}

need_root() {
  if [ -z "$ROOT" ] && [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' "install.sh must run as root. Use sudo, or set STAGE_ROOT for a staged install." >&2
    exit 1
  fi
}

install_packages() {
  if [ "${MUSTER_SKIP_PACKAGES:-0}" = "1" ]; then
    log "Skipping package install because MUSTER_SKIP_PACKAGES=1"
    return 0
  fi

  if [ -n "$ROOT" ]; then
    return 0
  fi

  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    if [ "$APPLIANCE_MODE" = "1" ]; then
      apt-get install -y curl ca-certificates mosquitto-clients nmap arp-scan network-manager avahi-daemon
    else
      apt-get install -y curl ca-certificates mosquitto-clients nmap arp-scan
    fi
  else
    log "apt-get not found; skipping package install"
  fi
}

prepare_source() {
  if [ -f "$SRC_ROOT/muster.yaml" ] && [ -f "$SRC_ROOT/src/porchlight-ha-mqtt-bridge" ]; then
    VERSION=$(tr -d '[:space:]' < "$SRC_ROOT/VERSION")
    RELEASE_DIR="$INSTALL_DIR/releases/$VERSION"
    return 0
  fi

  manifest_url="${INSTALL_MANIFEST_URL:-$DEFAULT_MANIFEST_URL}"
  mkdir -p "$TMP_DIR/src"
  fetch_file "$manifest_url" "$TMP_DIR/manifest.json"

  VERSION=$(json_value version "$TMP_DIR/manifest.json")
  artifact_url=$(json_value artifact_url "$TMP_DIR/manifest.json")
  artifact_sha=$(json_value sha256 "$TMP_DIR/manifest.json")

  if [ -z "$artifact_url" ]; then
    artifact_url=$(json_value archive "$TMP_DIR/manifest.json")
  fi

  if [ -z "$VERSION" ] || [ -z "$artifact_url" ] || [ -z "$artifact_sha" ]; then
    printf '%s\n' "Release manifest is missing version, artifact_url/archive, or sha256." >&2
    exit 1
  fi

  fetch_file "$artifact_url" "$TMP_DIR/artifact.tar.gz"
  actual_sha=$(sha256_file "$TMP_DIR/artifact.tar.gz")
  if [ "$actual_sha" != "$artifact_sha" ]; then
    printf '%s\n' "Downloaded artifact SHA256 mismatch." >&2
    exit 1
  fi

  tar -xzf "$TMP_DIR/artifact.tar.gz" -C "$TMP_DIR/src" --strip-components=1
  SRC_ROOT="$TMP_DIR/src"
  if [ ! -f "$SRC_ROOT/muster.yaml" ]; then
    printf '%s\n' "Release artifact did not contain a Porchlight source tree." >&2
    exit 1
  fi

  RELEASE_DIR="$INSTALL_DIR/releases/$VERSION"
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

install_static_webroot() {
  static_src="$SRC_ROOT/src/porchlight/webroot"
  static_dest=$(prefix_path "/var/lib/$PROJECT/www")

  if [ ! -d "$static_src" ]; then
    printf '%s\n' "Release is missing dashboard webroot: $static_src" >&2
    exit 1
  fi

  install -d -m 0755 "$static_dest"
  for source in "$static_src"/*; do
    [ -e "$source" ] || continue
    name=${source##*/}
    destination="$static_dest/$name"
    if [ -d "$source" ]; then
      rm -rf "$destination"
      cp -R "$source" "$destination"
    else
      install -m 0644 "$source" "$destination"
    fi
  done
}

need_root
prepare_source
install_packages

install_dir "$RELEASE_DIR/bin" 0755
install_dir "$RELEASE_DIR/src" 0755
install_dir "$RELEASE_DIR/systemd" 0755
install_dir "$RELEASE_DIR/etc" 0755
install_dir "$RELEASE_DIR/doc" 0755
install_dir "/etc/systemd/system" 0755
install_dir "/etc/$PROJECT" 0755
install_dir "/var/lib/$PROJECT/www" 0755
install_dir "/var/lib/muster/home-assistant-mqtt-bridge" 0755

install_file "$SRC_ROOT/src/porchlight-ha-mqtt-bridge" "$RELEASE_DIR/bin/porchlight-ha-mqtt-bridge" 0755
install_file "$SRC_ROOT/src/porchlight-ha-mqtt-bridge" "$RELEASE_DIR/src/porchlight-ha-mqtt-bridge" 0755
install_file "$SRC_ROOT/src/porchlight-scan" "$RELEASE_DIR/bin/porchlight-scan" 0755
install_file "$SRC_ROOT/src/porchlight-scan" "$RELEASE_DIR/src/porchlight-scan" 0755
install_file "$SRC_ROOT/src/porchlight-render" "$RELEASE_DIR/bin/porchlight-render" 0755
install_file "$SRC_ROOT/src/porchlight-render" "$RELEASE_DIR/src/porchlight-render" 0755
install_file "$SRC_ROOT/src/porchlight-health" "$RELEASE_DIR/bin/porchlight-health" 0755
install_file "$SRC_ROOT/src/porchlight-health" "$RELEASE_DIR/src/porchlight-health" 0755
install_file "$SRC_ROOT/src/porchlight-web" "$RELEASE_DIR/bin/porchlight-web" 0755
install_file "$SRC_ROOT/src/porchlight-web" "$RELEASE_DIR/src/porchlight-web" 0755
cp -R "$SRC_ROOT/src/porchlight" "$(prefix_path "$RELEASE_DIR/src/")"
install_file "$SRC_ROOT/bin/doctor.sh" "$RELEASE_DIR/bin/doctor.sh" 0755
install_file "$SRC_ROOT/bin/update.sh" "$RELEASE_DIR/bin/update.sh" 0755
install_file "$SRC_ROOT/bin/uninstall.sh" "$RELEASE_DIR/bin/uninstall.sh" 0755
install_file "$SRC_ROOT/bin/render-units.sh" "$RELEASE_DIR/bin/render-units.sh" 0755
install_file "$SRC_ROOT/bin/scan-now.sh" "$RELEASE_DIR/bin/scan-now.sh" 0755
install_file "$SRC_ROOT/bin/porchlightctl" "$RELEASE_DIR/bin/porchlightctl" 0755
install_file "$SRC_ROOT/bin/setup-ap.sh" "$RELEASE_DIR/bin/setup-ap.sh" 0755
install_file "$SRC_ROOT/bin/setup-apply.sh" "$RELEASE_DIR/bin/setup-apply.sh" 0755
install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.service" "$RELEASE_DIR/systemd/porchlight-ha-mqtt-bridge.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-ha-mqtt-bridge.timer" "$RELEASE_DIR/systemd/porchlight-ha-mqtt-bridge.timer" 0644
install_file "$SRC_ROOT/systemd/porchlight-scan.service" "$RELEASE_DIR/systemd/porchlight-scan.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-scan.timer" "$RELEASE_DIR/systemd/porchlight-scan.timer" 0644
install_file "$SRC_ROOT/systemd/porchlight-discover.service" "$RELEASE_DIR/systemd/porchlight-discover.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-discover.timer" "$RELEASE_DIR/systemd/porchlight-discover.timer" 0644
install_file "$SRC_ROOT/systemd/porchlight-deep-scan.service" "$RELEASE_DIR/systemd/porchlight-deep-scan.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-deep-scan.timer" "$RELEASE_DIR/systemd/porchlight-deep-scan.timer" 0644
install_file "$SRC_ROOT/systemd/porchlight-render.service" "$RELEASE_DIR/systemd/porchlight-render.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-render.timer" "$RELEASE_DIR/systemd/porchlight-render.timer" 0644
install_file "$SRC_ROOT/systemd/porchlight-health.service" "$RELEASE_DIR/systemd/porchlight-health.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-health.timer" "$RELEASE_DIR/systemd/porchlight-health.timer" 0644
install_file "$SRC_ROOT/systemd/porchlight-web.service" "$RELEASE_DIR/systemd/porchlight-web.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-setup-ap.service" "$RELEASE_DIR/systemd/porchlight-setup-ap.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-setup-apply.service" "$RELEASE_DIR/systemd/porchlight-setup-apply.service" 0644
install_file "$SRC_ROOT/systemd/porchlight-setup-apply.path" "$RELEASE_DIR/systemd/porchlight-setup-apply.path" 0644
install_file "$SRC_ROOT/etc/porchlight.env.example" "$RELEASE_DIR/etc/porchlight.env.example" 0644
install_file "$SRC_ROOT/etc/porchlight.mqtt.env.example" "$RELEASE_DIR/etc/porchlight.mqtt.env.example" 0644
install_file "$SRC_ROOT/etc/porchlight.setup.env.example" "$RELEASE_DIR/etc/porchlight.setup.env.example" 0644
install_file "$SRC_ROOT/README.md" "$RELEASE_DIR/README.md" 0644
install_file "$SRC_ROOT/README.md" "$RELEASE_DIR/doc/README.md" 0644
install_file "$SRC_ROOT/AGENTS.md" "$RELEASE_DIR/AGENTS.md" 0644
install_file "$SRC_ROOT/CODEX_TASK.md" "$RELEASE_DIR/CODEX_TASK.md" 0644
install_file "$SRC_ROOT/MUSTER.md" "$RELEASE_DIR/MUSTER.md" 0644
install_file "$SRC_ROOT/MUSTER.md" "$RELEASE_DIR/doc/MUSTER.md" 0644
install_file "$SRC_ROOT/SECURITY.md" "$RELEASE_DIR/SECURITY.md" 0644
install_file "$SRC_ROOT/SECURITY.md" "$RELEASE_DIR/doc/SECURITY.md" 0644
install_file "$SRC_ROOT/RELEASE.md" "$RELEASE_DIR/RELEASE.md" 0644
install_file "$SRC_ROOT/RELEASE.md" "$RELEASE_DIR/doc/RELEASE.md" 0644
install_file "$SRC_ROOT/muster.yaml" "$RELEASE_DIR/muster.yaml" 0644
install_file "$SRC_ROOT/VERSION" "$RELEASE_DIR/VERSION" 0644

mkdir -p "$INSTALL_DIR/releases"
rm -f "$CURRENT_LINK.next"
ln -s "releases/$VERSION" "$CURRENT_LINK.next"
rm -f "$CURRENT_LINK"
mv -f "$CURRENT_LINK.next" "$CURRENT_LINK"
install_static_webroot

if [ ! -f "$MQTT_CONFIG_FILE" ]; then
  install_file "$SRC_ROOT/etc/porchlight.mqtt.env.example" "/etc/$PROJECT/porchlight.mqtt.env" 0600
fi

if [ ! -f "$CONFIG_FILE" ]; then
  install_file "$SRC_ROOT/etc/porchlight.env.example" "/etc/$PROJECT/porchlight.env" 0644
fi

if [ ! -f "$(prefix_path "/etc/$PROJECT/enabled")" ]; then
  printf '%s\n' "true" > "$(prefix_path "/etc/$PROJECT/enabled")"
  chmod 0644 "$(prefix_path "/etc/$PROJECT/enabled")"
fi

if [ "$APPLIANCE_MODE" = "1" ] && [ ! -f "$(prefix_path "/etc/$PROJECT/setup.env")" ]; then
  suffix=$(hostname 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-' | tail -c 6)
  if [ -z "$suffix" ]; then
    suffix="setup"
  fi
  {
    printf 'PORCHLIGHT_APPLIANCE_MODE=1\n'
    printf 'PORCHLIGHT_MDNS_NAME=porchlight-%s.local\n' "$suffix"
    printf 'PORCHLIGHT_SETUP_SSID=Porchlight-%s\n' "$suffix"
    printf 'PORCHLIGHT_SETUP_PASSWORD=porchlight20\n'
    printf 'PORCHLIGHT_SETUP_WIFI_IFACE=wlan0\n'
  } > "$(prefix_path "/etc/$PROJECT/setup.env")"
  chmod 0600 "$(prefix_path "/etc/$PROJECT/setup.env")"
fi

if [ -z "$ROOT" ]; then
  cp "$SRC_ROOT"/systemd/*.service "$SYSTEMD_DIR/"
  cp "$SRC_ROOT"/systemd/*.timer "$SYSTEMD_DIR/"
  cp "$SRC_ROOT"/systemd/*.path "$SYSTEMD_DIR/"
  if [ "$APPLIANCE_MODE" = "1" ]; then
    if command -v hostnamectl >/dev/null 2>&1 && [ -f "/etc/$PROJECT/setup.env" ]; then
      # shellcheck disable=SC1091
      . "/etc/$PROJECT/setup.env"
      hostnamectl set-hostname "${PORCHLIGHT_MDNS_NAME%.local}" || true
    fi
  fi
  systemctl daemon-reload
  systemctl enable --now porchlight-web.service porchlight-discover.timer porchlight-scan.timer porchlight-render.timer porchlight-health.timer porchlight-ha-mqtt-bridge.timer
  if [ "$APPLIANCE_MODE" = "1" ]; then
    systemctl enable --now porchlight-setup-apply.path porchlight-setup-ap.service
  fi
fi

log "$PROJECT $VERSION installed"
