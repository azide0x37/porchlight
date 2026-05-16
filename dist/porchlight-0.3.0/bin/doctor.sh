#!/bin/sh
set -eu

PROJECT="porchlight"
ROOT="${MUSTER_ROOT:-${STAGE_ROOT:-}}"
CURRENT="$ROOT/opt/$PROJECT/current"
CONFIG_DIR="$ROOT/etc/$PROJECT"
MOCK_ROOT="${MUSTER_MOCK_ROOT:-${ROOT:-/tmp/porchlight-doctor}}"

check() {
  label="$1"
  shift
  if "$@"; then
    printf 'PASS %s\n' "$label"
  else
    printf 'FAIL %s\n' "$label" >&2
    exit 1
  fi
}

check "current release link exists" test -e "$CURRENT"
check "bridge executable exists" test -x "$CURRENT/bin/porchlight-ha-mqtt-bridge"
check "scan executable exists" test -x "$CURRENT/bin/porchlight-scan"
check "render executable exists" test -x "$CURRENT/bin/porchlight-render"
check "health executable exists" test -x "$CURRENT/bin/porchlight-health"
check "web executable exists" test -x "$CURRENT/bin/porchlight-web"
check "main config exists" test -f "$CONFIG_DIR/porchlight.env"
check "mqtt config exists" test -f "$CONFIG_DIR/porchlight.mqtt.env"
check "enabled flag exists" test -f "$CONFIG_DIR/enabled"
check "bridge service unit exists" test -f "$CURRENT/systemd/porchlight-ha-mqtt-bridge.service"
check "bridge timer unit exists" test -f "$CURRENT/systemd/porchlight-ha-mqtt-bridge.timer"
check "scan service unit exists" test -f "$CURRENT/systemd/porchlight-scan.service"
check "scan timer unit exists" test -f "$CURRENT/systemd/porchlight-scan.timer"
check "discover service unit exists" test -f "$CURRENT/systemd/porchlight-discover.service"
check "discover timer unit exists" test -f "$CURRENT/systemd/porchlight-discover.timer"
check "deep scan service unit exists" test -f "$CURRENT/systemd/porchlight-deep-scan.service"
check "deep scan timer unit exists" test -f "$CURRENT/systemd/porchlight-deep-scan.timer"
check "render service unit exists" test -f "$CURRENT/systemd/porchlight-render.service"
check "render timer unit exists" test -f "$CURRENT/systemd/porchlight-render.timer"
check "health service unit exists" test -f "$CURRENT/systemd/porchlight-health.service"
check "health timer unit exists" test -f "$CURRENT/systemd/porchlight-health.timer"
check "web service unit exists" test -f "$CURRENT/systemd/porchlight-web.service"

if [ -f "$CONFIG_DIR/porchlight.mqtt.env" ]; then
  HA_MQTT_ENABLE=$(sed -n 's/^HA_MQTT_ENABLE=//p' "$CONFIG_DIR/porchlight.mqtt.env" | head -n 1)
  MOSQUITTO_PUB=$(sed -n 's/^MOSQUITTO_PUB=//p' "$CONFIG_DIR/porchlight.mqtt.env" | head -n 1)
fi

if [ "${HA_MQTT_ENABLE:-0}" = "1" ]; then
  check "mqtt publish adapter available" command -v "${MOSQUITTO_PUB:-mosquitto_pub}"
fi

MUSTER_MOCK_ROOT="$MOCK_ROOT" "$CURRENT/bin/porchlight-ha-mqtt-bridge" --once >/dev/null
check "bridge emits state" test -s "$MOCK_ROOT/run/muster/home-assistant-mqtt-bridge/mqtt-outbox/porchlight_state.json"
MUSTER_MOCK_ROOT="$MOCK_ROOT" "$CURRENT/bin/porchlight-scan" --mode scan >/dev/null
check "sqlite ledger created" test -s "$MOCK_ROOT/var/lib/porchlight/porchlight.db"
check "dashboard snapshot rendered" test -s "$MOCK_ROOT/var/lib/porchlight/www/snapshot.json"
MUSTER_MOCK_ROOT="$MOCK_ROOT" "$CURRENT/bin/porchlight-health" >/dev/null
check "health writes muster status" test -s "$MOCK_ROOT/run/muster/status.json"

if command -v systemd-analyze >/dev/null 2>&1 && [ -z "$ROOT" ]; then
  systemd-analyze verify "$CURRENT"/systemd/*.service "$CURRENT"/systemd/*.timer
fi
