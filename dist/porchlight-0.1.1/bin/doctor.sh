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
check "main config exists" test -f "$CONFIG_DIR/porchlight.env"
check "mqtt config exists" test -f "$CONFIG_DIR/porchlight.mqtt.env"
check "enabled flag exists" test -f "$CONFIG_DIR/enabled"
check "service unit exists" test -f "$CURRENT/systemd/porchlight-ha-mqtt-bridge.service"
check "timer unit exists" test -f "$CURRENT/systemd/porchlight-ha-mqtt-bridge.timer"

if [ -f "$CONFIG_DIR/porchlight.mqtt.env" ]; then
  HA_MQTT_ENABLE=$(sed -n 's/^HA_MQTT_ENABLE=//p' "$CONFIG_DIR/porchlight.mqtt.env" | head -n 1)
  MOSQUITTO_PUB=$(sed -n 's/^MOSQUITTO_PUB=//p' "$CONFIG_DIR/porchlight.mqtt.env" | head -n 1)
fi

if [ "${HA_MQTT_ENABLE:-0}" = "1" ]; then
  check "mqtt publish adapter available" command -v "${MOSQUITTO_PUB:-mosquitto_pub}"
fi

MUSTER_MOCK_ROOT="$MOCK_ROOT" "$CURRENT/bin/porchlight-ha-mqtt-bridge" --once >/dev/null
check "bridge emits state" test -s "$MOCK_ROOT/run/muster/home-assistant-mqtt-bridge/mqtt-outbox/porchlight_state.json"

if command -v systemd-analyze >/dev/null 2>&1 && [ -z "$ROOT" ]; then
  systemd-analyze verify "$CURRENT/systemd/porchlight-ha-mqtt-bridge.service" "$CURRENT/systemd/porchlight-ha-mqtt-bridge.timer"
fi
