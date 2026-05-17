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
`0600`. Real broker publishing is disabled until `HA_MQTT_ENABLE=1`. The web
setup API can update broker settings, but responses only report whether a
password is set; they never return `MQTT_PASSWORD`.

## Setup API

`porchlight-web.service` exposes `/api/setup/*` for local appliance setup. The
API validates MQTT host, port, topic, and node fields before writing env files.
Wi-Fi writes are accepted only when appliance mode is enabled in
`/etc/porchlight/setup.env`. Setup side effects beyond file writes go through
`/run/porchlight/setup-action`, which is consumed by an allowlisted systemd
helper.

Normal installs do not enable the temporary setup access point. Appliance mode
uses NetworkManager to start a temporary setup AP only until
`/etc/porchlight/setup-complete` exists.

## Scan Safety

Active scanning is private-network only by default. Porchlight does not sweep
the whole LAN CIDR for ports during normal scans; it scans the bounded set of
hosts already observed through local evidence. UDP scans, NSE scripts, full TCP
scans, and Tailscale active scans are disabled by default.

## Config Preservation

`bin/install.sh`, `bin/update.sh`, and `bin/uninstall.sh` preserve
`/etc/porchlight` by default. `bin/uninstall.sh --purge` removes local config and
state.
