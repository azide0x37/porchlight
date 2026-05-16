# Porchlight LAN Directory Appliance

Porchlight exposes the scanner appliance to Home Assistant as one MQTT device:
`Porchlight LAN Directory`. It publishes summarized scanner facts and accepts
only a small allowlist of controls. Individual LAN hosts stay in Porchlight's
own dashboard instead of becoming transient Home Assistant entities.

## Home Assistant MQTT Bridge

The bridge reads:

- `/run/porchlight/status.json`
- `/run/muster/status.json`
- `/var/lib/porchlight/www/*.json`

It writes mock-first MQTT artifacts under:

- `/run/muster/home-assistant-mqtt-bridge/mqtt-outbox`
- `/run/muster/home-assistant-mqtt-bridge/mqtt-control`

Real broker publishing is disabled by default. Enable it in
`/etc/porchlight/porchlight.mqtt.env` with `HA_MQTT_ENABLE=1` after reviewing
the outbox payloads. The adapter is `mosquitto_pub`.

## Topics

- `homeassistant/device/porchlight/config`
- `porchlight/availability`
- `porchlight/state`
- `porchlight/enabled/state`
- `porchlight/cmd/enabled/set`
- `porchlight/cmd/scan_now`
- `porchlight/cmd/deep_scan`
- `porchlight/cmd/restart`
- `porchlight/control/result`

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

## Test

```sh
uv run python -m unittest discover -s tests
```
