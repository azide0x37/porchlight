# Security

Porchlight's Home Assistant integration exposes one scanner appliance, not every
LAN host as an entity.

## MQTT Controls

Controls are allowlisted by command name and exact payload:

- `enabled`: `ON` or `OFF`
- `scan_now`: `PRESS`
- `deep_scan`: `PRESS`
- `restart`: `PRESS`

Rejected control payloads are renamed to `*.rejected` and a result is published
to `porchlight/control/result`. The bridge never interpolates MQTT payloads into
shell commands.

## Broker Credentials

MQTT settings live in `/etc/porchlight/porchlight.mqtt.env`, installed with mode
`0600`. Real broker publishing is disabled until `HA_MQTT_ENABLE=1`.

## Config Preservation

`bin/install.sh`, `bin/update.sh`, and `bin/uninstall.sh` preserve
`/etc/porchlight` by default. `bin/uninstall.sh --purge` removes local config and
state.
