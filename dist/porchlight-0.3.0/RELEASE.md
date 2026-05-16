# Release

## 0.3.0

- Added the package-backed scanner implementation for config, discovery, Nmap
  XML parsing, SQLite storage, dashboard rendering, health, and web serving.
- Added `porchlight-render`, `porchlight-health`, `porchlight-web`,
  `scan-now.sh`, and `porchlightctl` runtime entrypoints.
- Added systemd timers for discovery, deep scan, render, and health, plus a
  systemd-owned local dashboard service.
- Installer now ships the Python package, scanner/web/health/render entrypoints,
  all systemd units, and apt scanner dependencies (`nmap`, `arp-scan`).
- Doctor now proves SQLite ledger creation, dashboard snapshot rendering, and
  Muster health status output.

## 0.2.0

- Added the first real scanner implementation through `src/porchlight-scan`.
- Added `porchlight-scan.service`, `porchlight-scan.timer`,
  `porchlight-discover.service`, and `porchlight-deep-scan.service`.
- Scanner now writes `/run/porchlight/status.json`, `/run/muster/status.json`,
  and `/var/lib/porchlight/www/*.json` using LAN neighbor and Tailscale data.
- Installer now deploys scanner units and enables the scan timer.

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
