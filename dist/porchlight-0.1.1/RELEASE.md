# Release

## 0.1.1

- Added apt-based installation for `mosquitto-clients` so real MQTT publishing
  has the configured `mosquitto_pub` adapter available.
- Added a doctor check that fails clearly when `HA_MQTT_ENABLE=1` and the
  configured MQTT publish adapter is missing.

## 0.1.0

- Initial Muster self-certified Porchlight appliance skeleton.
- Added Home Assistant MQTT bridge using mock-first discovery, state, and control artifacts.
- Added versioned install layout under `/opt/porchlight/releases/<version>/`.
- Added `doctor.sh`, `update.sh`, `uninstall.sh`, package generation, and self-certification tests.
