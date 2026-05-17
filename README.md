# Porchlight LAN Directory Appliance

Porchlight is a Muster self-certified small Linux appliance project for a LAN
directory scanner. It treats Home Assistant as a first-class presentation and
control surface without making Home Assistant the LAN database.

The current implementation includes the scanner, SQLite state ledger, static
dashboard renderer, local web service, health writer, and Home Assistant MQTT
bridge. Discovery is useful with only passive evidence, and active probing is
safety-gated by interface, private-CIDR, and maximum-prefix policy.

```text
scan + observe
  porchlight-discover.service  -> quick inventory mode
  porchlight-scan.service      -> bounded inventory + optional port scan
  porchlight-deep-scan.service -> scheduled deep mode
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

## Scanner

`porchlight-scan` writes SQLite observations and the state files consumed by the
Home Assistant bridge and dashboard:

- `/run/porchlight/status.json`
- `/run/muster/status.json`
- `/var/lib/porchlight/www/status.json`
- `/var/lib/porchlight/www/hosts.json`
- `/var/lib/porchlight/www/services.json`
- `/var/lib/porchlight/www/changes.json`
- `/var/lib/porchlight/www/snapshot.json`
- `/var/lib/porchlight/events.ndjson`
- `/var/lib/porchlight/porchlight.db`

The first scanner pass uses sources already visible from the appliance:

- `ip -j neigh show` for LAN neighbor/ARP evidence
- `ip -j route show default` and `ip -j addr show` for gateway and CIDR
- `tailscale status --json` for tailnet devices
- `arp-scan --localnet` when available
- `getent hosts <ip>` for reverse-DNS/PTR names
- `nmap -sT -n --open` for common ports on discovered hosts

This is intentionally conservative. By default Porchlight refuses active scans
outside private IPv4 space. It does not sweep the whole CIDR for ports; it scans
the bounded set of hosts already observed through ARP, neighbor, gateway, or
Tailscale evidence.

## Dashboard

`porchlight-web.service` serves the static dashboard from
`/var/lib/porchlight/www` on port `8765`. The renderer writes plain JSON and
the hosted HTML/CSS/JS assets adapted from `azide0x37/porchlight-dashboard`, so
the web service does not need scanner privileges or a Node runtime. The
dashboard reads `/status.json`, `/hosts.json`, `/services.json`,
`/changes.json`, and `/snapshot.json` at runtime, which keeps the appliance UI
in sync with the latest scanner render.

The packaged webroot vendors the dashboard fonts and PWA icon set locally,
uses iOS safe-area metadata, and serves HTML/CSS/JS/JSON with no-store cache
headers so mobile and installed-PWA clients do not mix markup from one release
with styles from another.

Service rows include categorized HTTP, RTSP, MQTT, and common internal network
ports. HTTP/HTTPS services are linked directly from the dashboard, and
Porchlight tries to use the root page `<title>` as the link text when the
landing page is reachable.

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
- `sensor.porchlight_http_services`
- `sensor.porchlight_rtsp_services`
- `sensor.porchlight_mqtt_services`
- `sensor.porchlight_internal_services`
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

From a published release:

```sh
curl -fsSL https://github.com/azide0x37/porchlight/releases/latest/download/install.sh | sudo sh
```

The installer writes the active release to
`/opt/porchlight/releases/<version>/`, updates `/opt/porchlight/current`,
installs required MQTT/scanner packages on apt-based hosts, installs the systemd
units, and enables the web service plus scheduled discovery, scan, render,
health, and MQTT bridge timers.

For staged verification:

```sh
MUSTER_ROOT=/tmp/porchlight-stage ./bin/install.sh
```

For staged verification without package installation:

```sh
MUSTER_SKIP_PACKAGES=1 MUSTER_ROOT=/tmp/porchlight-stage ./bin/install.sh
```

## Health Check

```sh
sudo /opt/porchlight/current/bin/doctor.sh
```

The doctor verifies the install layout, config files, systemd unit presence,
mock bridge output, SQLite ledger creation, rendered dashboard snapshot, and
Muster health status output.

## Update

`bin/update.sh` expects an update manifest at
`/etc/porchlight/update-manifest.json` unless `UPDATE_MANIFEST_FILE` is set.

```json
{"version":"0.1.1","artifact_url":"/path/to/porchlight-0.1.1.tar.gz","sha256":"..."}
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

- `dist/porchlight-1.1.0/`
- `dist/porchlight-1.1.0.tar.gz`
- `dist/porchlight-1.1.0.tar.gz.sha256`
- `dist/install.sh`
- `dist/manifest.json`

## Self-Certification

| Requirement | Status | Evidence |
| --- | --- | --- |
| systemd owns lifecycle | PASS | `systemd/porchlight-ha-mqtt-bridge.service` calls `/opt/porchlight/current/bin/porchlight-ha-mqtt-bridge` |
| systemd timer owns scheduled refresh | PASS | `systemd/porchlight-scan.timer` and `systemd/porchlight-ha-mqtt-bridge.timer` run scan and publish loops |
| config under `/etc/porchlight` | PASS | `etc/porchlight.mqtt.env.example`, `bin/install.sh` preserves existing config |
| runtime under `/opt/porchlight/releases/<version>` | PASS | `bin/install.sh` installs to `/opt/porchlight/releases/$(VERSION)` |
| `/opt/porchlight/current` active link | PASS | `bin/install.sh` updates the symlink after staging release files |
| units call `/opt/porchlight/current/bin/...` | PASS | `systemd/porchlight-ha-mqtt-bridge.service` `ExecStart` |
| scanner writes state ledger | PASS | `src/porchlight-scan`, `src/porchlight/store.py`, `tests/test_scan.py` |
| static dashboard is rendered | PASS | `src/porchlight-render`, `src/porchlight/render.py`, `src/porchlight/webroot`, vendored fonts/icons, `systemd/porchlight-render.timer` |
| local web dashboard is systemd-owned | PASS | `src/porchlight-web`, `src/porchlight/web.py` no-store headers for mutable assets, `systemd/porchlight-web.service` |
| appliance health is written | PASS | `src/porchlight-health`, `systemd/porchlight-health.timer` |
| installer idempotent | PASS | `make test` runs staged install; installer only creates default config when missing |
| broker and scanner dependencies handled | PASS | `bin/install.sh` installs `mosquitto-clients`, `nmap`, and `arp-scan` on apt hosts; `bin/doctor.sh` checks `MOSQUITTO_PUB` when `HA_MQTT_ENABLE=1` |
| updater verifies and rolls back | PASS | `bin/update.sh` checks SHA256, runs `doctor.sh`, and restores previous `current` on failure |
| uninstaller preserves config by default | PASS | `bin/uninstall.sh` only removes `/etc/porchlight` with `--purge` |
| Python justified and run through `uv` | PASS | bridge uses Python for JSON/discovery payload generation; `make test` runs `uv run python -m unittest discover -s tests` |
| MPL atoms documented | PASS | `muster.yaml`, `MUSTER.md`, and this README name the relevant MPL patterns |
| README self-certifies compliance | PASS | this table |
| tests current | PASS | `make test` |
| package and release assets current | PASS | `make package` writes `dist/install.sh`, `dist/manifest.json`, tarball, and SHA256 |
