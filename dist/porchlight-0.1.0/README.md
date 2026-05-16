# Porchlight LAN Directory Appliance

Porchlight is a Muster self-certified small Linux appliance project for a LAN
directory scanner. It treats Home Assistant as a first-class presentation and
control surface without making Home Assistant the LAN database.

The current implementation is the operational skeleton and Home Assistant MQTT
bridge. Scanner services will feed the same state ledger and sidecar snapshots
that the bridge already consumes.

```text
scan + observe
  porchlight-discover.service
  porchlight-scan.service
  porchlight-deep-scan.service
        |
        v
state + interpretation
  SQLite
  /run/porchlight/status.json
  /run/muster/status.json
  /var/lib/porchlight/www/*.json
        |
        +--> local web dashboard
        |
        +--> T2R6 Home Assistant MQTT Bridge
              publishes HA discovery
              publishes appliance state
              accepts narrow controls
```

## Muster Status

This repo follows the [Muster](https://github.com/azide0x37/muster) service
repository contract:

- systemd owns service lifecycle.
- systemd timers own scheduled refresh.
- config lives under `/etc/porchlight/`.
- runtime code installs under `/opt/porchlight/releases/<version>/`.
- `/opt/porchlight/current` points to the active release.
- `bin/install.sh` is idempotent.
- `bin/update.sh` verifies SHA256 and rolls back on failed health checks.
- `bin/uninstall.sh` preserves config unless called with `--purge`.
- Python is used for structured JSON/MQTT payload generation and is run through `uv`.
- this README self-certifies the implementation with evidence.

The formal local contract is in `MUSTER.md`. The implementation mapping is in
`muster.yaml`.

## Pattern Mapping

Porchlight uses Muster Pattern Library vocabulary instead of project-specific
names where the library already has a shape:

| Role | MPL pattern |
| --- | --- |
| Appliance bundle | `T3C1.edge-appliance-bundle` |
| Local edge control plane | `T2R3.edge-control-plane` |
| Home Assistant presentation and controls | `T2R6.home-assistant-mqtt-bridge` |
| Service lifecycle | `C1.service-capsule` |
| Scheduled refresh | `C2.persistent-tick`, `T2C3.scheduled-herald` |
| Inspectable failure/control state | `C5.failure-ratchet` |
| Install/update/uninstall/doctor lifecycle | `C6.lifecycle-capsule` |
| Scanner truth source | `R4.state-ledger` |
| Local state snapshots | `T2C5.local-sidecar-bridge` |

## Home Assistant MQTT Bridge

The bridge exposes one Home Assistant device:

`Porchlight LAN Directory`

It publishes summarized appliance facts:

- `sensor.porchlight_health`
- `sensor.porchlight_scan_state`
- `sensor.porchlight_last_scan`
- `sensor.porchlight_hosts_seen`
- `sensor.porchlight_active_hosts`
- `sensor.porchlight_open_ports`
- `sensor.porchlight_new_hosts`
- `sensor.porchlight_changed_services`
- `sensor.porchlight_network_cidr`
- `sensor.porchlight_gateway`
- `binary_sensor.porchlight_scanner_online`
- `binary_sensor.porchlight_degraded`
- `binary_sensor.porchlight_changes_detected`
- `switch.porchlight_enabled`
- `button.porchlight_scan_now`
- `button.porchlight_deep_scan`
- `button.porchlight_restart_service`

It does not expose every discovered LAN device as a Home Assistant device.
Phones, TVs, containers, bridges, and printers belong in the Porchlight
dashboard, not as transient Home Assistant entity churn.

## MQTT Topics

- `homeassistant/device/porchlight/config`
- `porchlight/availability`
- `porchlight/state`
- `porchlight/enabled/state`
- `porchlight/cmd/enabled/set`
- `porchlight/cmd/scan_now`
- `porchlight/cmd/deep_scan`
- `porchlight/cmd/restart`
- `porchlight/control/result`

## Mock-First Operation

The bridge reads:

- `/run/porchlight/status.json`
- `/run/muster/status.json`
- `/var/lib/porchlight/www/*.json`

It always writes mockable MQTT artifacts under:

- `/run/muster/home-assistant-mqtt-bridge/mqtt-outbox`
- `/run/muster/home-assistant-mqtt-bridge/mqtt-control`

Real broker publishing is disabled by default. Enable it in
`/etc/porchlight/porchlight.mqtt.env` with `HA_MQTT_ENABLE=1` after reviewing
the outbox payloads. The adapter is `mosquitto_pub`.

## Controls

Allowed command payloads are exact and fail closed:

- `enabled`: `ON` or `OFF`
- `scan_now`: `PRESS`
- `deep_scan`: `PRESS`
- `restart`: `PRESS`

The local file-control adapter reads command files such as
`mqtt-control/scan_now.cmd`. In apply mode it maps them to explicit local
actions:

- `scan_now` -> `systemctl start porchlight-scan.service`
- `deep_scan` -> `systemctl start porchlight-deep-scan.service`
- `restart` -> `systemctl restart porchlight-web.service porchlight-health.service`
- `enabled` -> write `/etc/porchlight/enabled`

The bridge never accepts arbitrary service names or shell fragments from MQTT.

## Install

From a checkout:

```sh
sudo ./bin/install.sh
```

The installer writes the active release to
`/opt/porchlight/releases/<version>/`, updates `/opt/porchlight/current`, installs
the systemd units, and enables `porchlight-ha-mqtt-bridge.timer`.

For staged verification:

```sh
STAGE_ROOT=/tmp/porchlight-stage ./bin/install.sh
```

## Health Check

```sh
sudo /opt/porchlight/current/bin/doctor.sh
```

The doctor verifies the install layout, config files, systemd unit presence, and
mock bridge output.

## Update

`bin/update.sh` expects an update manifest at
`/etc/porchlight/update-manifest.json` unless `UPDATE_MANIFEST_FILE` is set.

```json
{"version":"0.1.0","archive":"/path/to/porchlight-0.1.0.tar.gz","sha256":"..."}
```

The updater verifies SHA256, installs the new release, runs `doctor.sh`, and
restores the previous `/opt/porchlight/current` link if the health check fails.

## Uninstall

```sh
sudo /opt/porchlight/current/bin/uninstall.sh
```

This disables units and removes installed code while preserving
`/etc/porchlight`. To remove local config and state too:

```sh
sudo /opt/porchlight/current/bin/uninstall.sh --purge
```

## Test

```sh
make test
```

This runs the Python regression suite through `uv`, shell syntax checks, and a
staged installer pass.

## Package

```sh
make package
```

This writes:

- `dist/porchlight-0.1.0/`
- `dist/porchlight-0.1.0.tar.gz`
- `dist/porchlight-0.1.0.tar.gz.sha256`
- `dist/manifest.json`

## Self-Certification

| Requirement | Status | Evidence |
| --- | --- | --- |
| systemd owns lifecycle | PASS | `systemd/porchlight-ha-mqtt-bridge.service` calls `/opt/porchlight/current/bin/porchlight-ha-mqtt-bridge` |
| systemd timer owns scheduled refresh | PASS | `systemd/porchlight-ha-mqtt-bridge.timer` runs the bridge every minute after boot |
| config under `/etc/porchlight` | PASS | `etc/porchlight.mqtt.env.example`, `bin/install.sh` preserves existing config |
| runtime under `/opt/porchlight/releases/<version>` | PASS | `bin/install.sh` installs to `/opt/porchlight/releases/$(VERSION)` |
| `/opt/porchlight/current` active link | PASS | `bin/install.sh` updates the symlink after staging release files |
| units call `/opt/porchlight/current/bin/...` | PASS | `systemd/porchlight-ha-mqtt-bridge.service` `ExecStart` |
| installer idempotent | PASS | `make test` runs staged install; installer only creates default config when missing |
| updater verifies and rolls back | PASS | `bin/update.sh` checks SHA256, runs `doctor.sh`, and restores previous `current` on failure |
| uninstaller preserves config by default | PASS | `bin/uninstall.sh` only removes `/etc/porchlight` with `--purge` |
| Python justified and run through `uv` | PASS | bridge uses Python for JSON/discovery payload generation; `make test` runs `uv run python -m unittest discover -s tests` |
| MPL atoms documented | PASS | `muster.yaml`, `MUSTER.md`, and this README name the relevant MPL patterns |
| README self-certifies compliance | PASS | this table |
| tests current | PASS | `make test` |
| package current | PASS | `make package` |
