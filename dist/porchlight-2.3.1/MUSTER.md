# Muster Contract

Porchlight is a self-certified Muster project for a small Linux service appliance.

## Project Mapping

Porchlight implements a LAN directory appliance:

```text
scan + observe
  -> SQLite and sidecar state
  -> local dashboard JSON
  -> optional AI analysis sidecar
  -> Home Assistant MQTT bridge
```

The Home Assistant surface is intentionally one appliance device with summarized
facts and narrow controls. Discovered LAN devices remain in the Porchlight
dashboard instead of becoming Home Assistant entities.

## MPL Patterns

The closest Muster Pattern Library vocabulary is:

- `T3C1.edge-appliance-bundle`: overall appliance shape.
- `T2R3.edge-control-plane`: local control plane and sidecar state.
- `T2R6.home-assistant-mqtt-bridge`: Home Assistant MQTT discovery, state, and scoped controls.
- `T2R7.ai-analysis-sidecar`: draft opt-in AI analysis worker for local snapshots.
- `C1.service-capsule`: scanner, renderer, health, web, and bridge units are systemd-owned.
- `C2.persistent-tick`: timers own discovery, scan, render, health, MQTT refresh, and AI analysis refresh.
- `C5.failure-ratchet`: rejected controls and failed publish attempts leave inspectable state.
- `C6.lifecycle-capsule`: install, update, uninstall, and doctor scripts.
- `R4.state-ledger`: SQLite and JSON state are the source of truth for presentation.
- `T2C5.local-sidecar-bridge`: `/run` and `/var/lib/porchlight/www` snapshots feed presentation surfaces.
- `T2C3.scheduled-herald`: repeated state publishing through systemd timer.

## Contract Status

- systemd owns service lifecycle through `porchlight-web.service`,
  `porchlight-health.service`, `porchlight-render.service`,
  `porchlight-scan.service`, `porchlight-ai-analysis.service`, and
  `porchlight-ha-mqtt-bridge.service`.
- systemd owns scanner lifecycle through `porchlight-scan.service`,
  `porchlight-discover.service`, and `porchlight-deep-scan.service`.
- systemd timers own scheduled refresh through `porchlight-discover.timer`,
  `porchlight-scan.timer`, `porchlight-deep-scan.timer`,
  `porchlight-render.timer`, `porchlight-health.timer`, and
  `porchlight-ha-mqtt-bridge.timer`, and `porchlight-ai-analysis.timer`.
- Scanner state is durable in `/var/lib/porchlight/porchlight.db` and
  `/var/lib/porchlight/events.ndjson`.
- Rendered sidecar state lives in `/var/lib/porchlight/www/*.json`.
- Configuration lives under `/etc/porchlight/`.
- Runtime code installs under `/opt/porchlight/releases/<version>/`.
- `/opt/porchlight/current` points to the active release.
- systemd units call `/opt/porchlight/current/bin/...`.
- `bin/install.sh` is idempotent and preserves existing config.
- `bin/update.sh` verifies SHA256, installs the new release, runs `doctor.sh`, and rolls back `current` on failed health checks.
- `bin/uninstall.sh` stops units and removes installed code while preserving config unless called with `--purge`.
- Python is used for structured JSON and MQTT payload generation, and tests run through `uv`.
- `README.md` self-certifies compliance with command evidence.
