# Guest mode backend and Home Assistant handoff

Status: the combined backend, guest screen, and infrastructure workstream shipped
in the local v2.6.1 deployment (2026-10-17). Authenticated MQTT, the restricted
HTTPS route, and live UniFi QR retrieval are verified. The built-in HA Cast
receiver failed to launch on the household TV. The commissioned DashCast path
now wakes the TV from OFF and receives a matching screen heartbeat in about
47 seconds; repeated ON preserves the session. The operator confirmed the full
guest screen, including Wi-Fi QR and room temperatures. Phone QR joining and
spoken Alexa commands remain untested. No GitHub release is published here.

## Ownership and changes from the original plan

Home Assistant owns the requested state, session, Vizio power, and Cast action.
Porchlight accepts only bounded presentation snapshots and reports presentation
status. It never receives HA service names, shell commands, URLs, or Wi-Fi
credentials over MQTT, and it never changes climate settings.

The Alexa control is now a **native HA template switch**, backed by a serialized
ON/OFF script. This replaces the staged MQTT command switch: an old retained
ON command cannot wake the TV on reconnect because there is no command-topic
subscriber. Do not install the original staged MQTT switch alongside this one.
The diagnostic MQTT sensor joins the existing `porchlight` device. The template
switch is an independent HA entity named `Guest Mode`.

The inspected household display path is Vizio SmartCast power control followed
by Home Assistant's Google Cast integration. `cast.show_lovelace_view` accepts a
Home Assistant dashboard path and view path, not an arbitrary Porchlight HTML
URL. The screen supports an HTTPS iframe and the backend heartbeat contract.
For receivers that cannot launch HA Cast, an operator-owned
`script.porchlight_guest_open_display` takes precedence over HA Cast. This fixed
hook runs only after the same power, session, and commissioning checks. It must
launch the restricted screen and must not publish its private URL in entity
attributes or MQTT. The guest backend still accepts no remote control commands.

## Backend

`porchlight-guest.service` owns a continuous MQTT receiver and a separate HTTP
listener. It starts disabled; `/etc/porchlight/guest.json` and `guest.env` are
installed only if absent, mode 0600, and preserved through update/uninstall.
Real config must be owner-only. Runtime diagnostic state is written atomically
to `/run/porchlight/guest/status.json`, mode 0600. Credentials are never written
to that file or to scanner/static webroot data. Presentation state stays in
memory and is not replayed at startup.

To configure, edit the installed examples locally:

- Set `enabled: true`, supply a random 32–128 character URL-safe `access_token`,
  and explicitly list up to eight `allowed_climate_entities`.
- `wifi: null` is supported when using the native UniFi image proxy described
  below. Local guest credentials are an optional fallback; never copy appliance
  setup credentials automatically.
- Set the broker in `porchlight.mqtt.env` and `HA_MQTT_ENABLE=1`. Authentication is
  required by default. Optional `MQTT_CAFILE`, `MQTT_CERTFILE`, `MQTT_KEYFILE` use
  certificate verification. Anonymous MQTT requires the explicit local-only
  testing override `GUEST_MQTT_ALLOW_ANONYMOUS=1`.
- The listener defaults to `127.0.0.1:8766`. Keep the origin private. The presenter
  needs trusted routing/TLS and a way to provide its bearer token. Do not expose
  the admin listener or put tokens in query strings.
- Validate with `uv run python src/porchlight-guest --apply --check`, then restart
  `porchlight-guest.service`. Mosquitto 2.x clients with MQTT 5 support are required.

The adapter subscribes only to `<HA_BASE_TOPIC>/guest/presentation`, uses a clean
MQTT session, bounded packets/frames, reconnect/backoff, and an `offline` Last
Will on `/guest/availability`. Credentials are in short-lived 0600 client config
files, not command-line arguments. Availability becomes online after a valid
snapshot; disconnect/expiry produces unavailable status. `/guest/status` is
non-retained. No new network adapter for existing scanner command topics exists.

Snapshots are schema version 1, maximum 16 KiB, with exact fields as in
[`presentation.example.json`](../../examples/guest-mode/presentation.example.json).
Retained snapshots, duplicates, out-of-order timestamps, malformed values,
unallowlisted climate entities, timestamps over five seconds in the future, and
snapshots aged 45 seconds or more are rejected. Rejection does not extend the
last valid deadline. Local monotonic expiry also protects against clock rollback.
Unavailable HVAC values become null, not zero. ON→OFF immediately removes all
Wi-Fi/HVAC/voice content from API responses. A valid reconnect snapshot can
restore presentation state but cannot wake or power-cycle the TV.

## Guest screen API

All data/heartbeat requests require `Authorization: Bearer <access_token>`.
Responses use `Cache-Control: no-store`. There is no CORS, cookie auth, arbitrary
file serving, or forwarding to the admin dashboard.

| Endpoint | Contract |
| --- | --- |
| `GET /healthz` | Process liveness; returns `ui_available: true` now that the screen is served by the same listener. |
| `GET /api/guest/status` | Sanitized state, session, error, freshness, and remaining lifetime. |
| `GET /api/guest` | Same status plus welcome/title, allowlisted HVAC, voice examples, Wi-Fi and escaped `qr_payload` only during a fresh enabled session. |
| `POST /api/guest/heartbeat` | JSON `session_id`, `presentation_id`, `visible` (boolean). Rejects old/inactive sessions. |

The listener serves only the allowlisted screen assets under `/guest/` (see
`src/porchlight/guest_web.py`) and returns 404 for all admin/setup endpoints,
scanner JSON, traversal paths, and query-token requests. The screen generates the
QR locally from `qr_payload`, inserts labels as text, polls every five seconds,
and blanks all content when its local freshness deadline or connection fails.
See the README "Guest Screen" section and
[the Claude → Codex handoff note](notes/2026-10-17-guest-screen-handoff-to-codex.md). Send a visible heartbeat at least every
10 seconds only after rendering; a hidden/neutral view sends `visible: false`.

`starting` means ON but no current presenter acknowledgement. After 30 seconds
it becomes `degraded`; `active` requires a matching acknowledgement from the
last 20 seconds. Reconnect, expiry, mode changes, and session changes invalidate
old presentation IDs. This is presenter-reported liveness, not independent proof
that physical pixels are visible. Never equate TV power with an active display.

## Home Assistant tenant

The canonical package is [`homeassistant/porchlight_guest.yaml`](../../homeassistant/porchlight_guest.yaml).
It uses the inspected `media_player.visio_tv_2` for power, `media_player.visio_tv`
for Cast, and the explicitly listed living-room thermostat, bedroom AC, and
kitchen AC in °F. Adapt these values and MQTT topics for other installations.

Install into `/config/packages/porchlight_guest.yaml` after backing up any prior
file and confirming `homeassistant: packages: !include_dir_named packages` is
already configured. Run `ha core check` before loading. The controller defaults
OFF on first install and restores its commissioning choice on restart. Display
readiness and dashboard/view paths also restore their commissioned values.
Requested mode always starts OFF, preventing restart-triggered TV wake. Commission
the controller only after checking the power target. Leave display readiness OFF
until a compatible guest view has been verified.

Expose only `switch.porchlight_guest_mode` through the existing HA Cloud Alexa
integration, with the name `Guest Mode`. Verify that all `script.porchlight_guest_*`,
helpers, diagnostics, and automations remain unexposed. Use the existing UI
exposure controls; adding a new YAML cloud filter would replace household-wide
exposure behavior. Voice discovery and spoken acceptance require the actual Echo.

ON is idempotent: repeated ON preserves the session and does not repeat the TV
sequence. OFF is serialized, cancels pending TV activation, and publishes a fresh
OFF snapshot. Vizio wake is attempted once, with a 75-second wait (covering its
30-second power-state polling interval) and three-second
settling delay. A session/commissioning check precedes Cast. While UI readiness
is OFF, TV diagnostics report `ui_pending` after successful wake. Otherwise the
script calls the fixed display hook if installed, otherwise HA Cast, then waits up
to 30 seconds for a matching presenter.
Failure is `tv_wake_timeout` or `display_unconfirmed`; neither reports active.
OFF leaves TV power and input alone; the screen clears its content on the next
poll, and also clears locally when its freshness deadline expires.

### DashCast adapter

The household TV launches the standard Cast receiver and DashCast, but times out
before the HA Lovelace receiver starts. The tested alternative uses the
[DashCast integration](https://github.com/AlexxIT/DashCast), v1.1.1, through HACS.
Create an operator-owned HA script with ID `porchlight_guest_open_display` that
calls `dash_cast.load_url` for the same allowlisted TV and the private HTTPS
`/guest/#t=…` link. Use `force: false` and `reload_seconds: 0`; the screen handles
refresh and privacy expiry. Store the URL in private HA script configuration or
secrets, not an `input_text` helper, repository, or MQTT message. The private link
is provided to the receiver running on the TV. Never use the HA access token as
the display token.

Do not enable the display commissioning helper merely because Cast reports an
app name. Require the screen's matching session heartbeat and physical acceptance.
Remove the hook to return to the HA Cast dashboard/view adapter.

The household also has a Laboratory camera automation targeting this TV. Its
priority/restoration interaction with Guest Mode remains an acceptance check;
this package does not silently rewrite that separate automation.

## Verification and remaining acceptance

`make test` covers backend validation, auth/route isolation, stale/retained data,
OFF, session acknowledgements, config preservation, and YAML/Jinja projections.
The template harness supplies HA-like functions; runtime validation in the actual
tenant is separate. `make package DIST=/tmp/porchlight-guest-package` includes the
backend, unit, defaults, HA package, examples, and this handoff.

A real temporary loopback Mosquitto smoke test (`uv run python tests/guest_mqtt_smoke.py`) verifies retained replay rejection,
live ON/OFF, broker loss/reconnect, and graceful offline shutdown. The deployed
public API and native QR image pass ON/OFF checks, including rejection of missing
authentication and admin routes. The automated cold wake, matching presenter
heartbeat, repeated-ON session preservation, and physical full-screen rendering
are verified. A phone joining through the on-TV QR, spoken Alexa commands, and
display coexistence remain separate commissioning checks.

The HVAC status chips show the current action only, without the mode or separator
dot. Cooling and idle/range fixtures fit the three-room 1280×720 layout. This
screen-only correction was deployed over v2.6.1 after the operator reported
overflow; the private receipt records its checksum and rollback copy.

Rollback: turn Guest Mode OFF and unexpose its switch; disable the controller,
stop the guest service, and restore/remove only this HA package. Preserve guest
configuration and existing scanner MQTT topics. Remove only this feature's
retained `/guest/requested` and `/guest/availability` state if needed.

Commissioning must verify HA configuration, Alexa exposure, repeated-ON session
preservation, OFF cancellation, cold TV wake, and the selected Wi-Fi QR image.
Keep the guest service disabled until authenticated MQTT is configured. It can
then receive private OFF snapshots while the HTTPS route is prepared. Keep the
HA display commissioning gate off until the route and iframe are verified.
Deployment receipts belong in private operator records.
See [the backend reply to Fable](notes/2026-10-17-backend-reply-to-fable.md)
for the adapter decision, 11 HVAC fixtures, service restart semantics, and
remaining UI/voice/QR commissioning.

References: [HA template switch](https://www.home-assistant.io/integrations/template/#switch),
[HA Google Cast](https://www.home-assistant.io/integrations/cast/),
[Nabu Casa Alexa exposure](https://support.nabucasa.com/hc/en-us/articles/25619363899677-Configuring-Amazon-Alexa-to-work-with-Home-Assistant),
[Mosquitto subscriber](https://mosquitto.org/man/mosquitto_sub-1.html).

## Spotify and native UniFi QR extensions

Schema 1 accepts an optional `spotify` object only while enabled. Its exact fields
are `id`, `state` (`playing` or `paused`), `title`, `artist`, `album`, `source`,
`duration`, and `position`. The media entity must appear in local
`allowed_spotify_entities`; text is limited to 256 characters and numeric times
to 0–86400 seconds. The HA template selects a playing Spotify integration entity
before a paused one. It omits the object when idle. No artwork URL, OAuth token,
queue command, or playback control is accepted.

The view adds `spotify.jam` only for a host-supplied invite matching the current
session, bounded by both wall and monotonic expiry. The owner-facing Settings
form binds a new link to fresh receiver state for four hours. Ending Guest Mode
or starting another session hides it. Hosts must clear invitations when ending
a Jam early: neither HA nor Spotify's public API reports Jam status or invitations.

The native HA QR proxy uses verified HTTPS and a token in 0600 `guest.env`.
Owner settings are available at `/api/setup/guest-ha`; responses expose only a
token-present flag. The worker reads exactly the configured `image.*` entity,
rejects redirects and non-PNG/oversized images, and discards responses from an old
presentation. `/api/guest/wifi-qr` requires the guest bearer and fresh enabled
state. The browser authenticates its fetch and uses a revocable blob URL.
HA's QR takes precedence over local credentials while fresh. Polling at both
hops is 15 seconds; failures clear the cached image. Bad HA authentication stops
retries until settings are corrected and the service restarts.

Sources: [HA Spotify implementation](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/spotify/media_player.py),
[Spotify queue API](https://developer.spotify.com/documentation/web-api/reference/add-to-queue),
[Spotify Jam invitations](https://support.spotify.com/cg-en/article/jam/),
[HA UniFi images](https://www.home-assistant.io/integrations/unifi/#image).

## Cross-agent notes

- [2026-10-17 guest screen handoff (Claude → Codex)](notes/2026-10-17-guest-screen-handoff-to-codex.md):
  what the screen needs from the backend (real HVAC fixtures, a display adapter
  that can open the screen URL, docs alignment) and which files each agent owns.
- [2026-10-17 backend reply (Codex → Claude)](notes/2026-10-17-backend-reply-to-fable.md):
  fixtures, the Cast `webpage`-card adapter behind an HTTPS proxy, UniFi QR image, restart notes.
- [2026-10-17 screen reply (Claude → Codex)](notes/2026-10-17-screen-reply-to-codex.md):
  fixture-driven rendering rules, relative URLs for the proxy, a Wi-Fi contract that
  carries either a local payload or a same-origin HA QR image, open owner decisions.
