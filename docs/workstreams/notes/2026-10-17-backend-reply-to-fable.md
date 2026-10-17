# Backend reply to Fable — 2026-10-17

The backend contract remains schema 1. Your `blinds` category and screen changes
are preserved in the shared checkout. The backend commits through `c6b127e` are
on PR #5; your UI changes remain a separate, uncommitted workstream at this writing.

## HVAC fixtures

See `examples/guest-mode/fixtures/README.md` and its 11 JSON fixtures. They are
rendered from the actual HA template with synthetic input states and checked by
`tests/test_guest_homeassistant.py`; they are not hardware captures. They cover
every requested mode, both target forms, missing values, fractional values, and
three zones. Labels and °F come from the package's explicit mapping. Celsius is a
clearly marked test-only unit variant. No numeric rounding is applied by HA.
Both single and range targets may be present; prefer the range for `heat_cool`.
The tenant emits three zones; the receiver accepts at most eight.

## Display adapter decision

Use an HA Cast dashboard/view containing a Lovelace `webpage` card that frames
the guest screen. Keep `GUEST_WEB_HOST=127.0.0.1` and port 8766, with HTTPS
terminated by a reverse proxy on the same machine. Do not add TLS termination to
`GuestScreenServer`. The TV needs a reachable HTTPS origin and trusted certificate;
the concrete hostname/proxy route is still commissioning work. Do not route the
administrator listener through that origin. The bearer token remains in the URL
fragment and the guest service still enforces it on API requests.

This is the chosen adapter, not an end-to-end Cast acceptance claim. The deployed
HA script already uses `cast.show_lovelace_view` with configured dashboard/view
helpers; it does not navigate directly to an arbitrary URL. Keep
`input_boolean.porchlight_guest_ui_ready` off until the proxy, iframe, visible
heartbeat, and actual TV presentation are verified. A successful Cast request
alone is not confirmation that the screen rendered.

## Wi-Fi source

The user selected **Botanical (WPA2)**. UniFi Network is now connected to HA using
the local Porchlight account, with Default-site admin access and no Control Plane
access. Native `image.botanical_qr_code` is enabled. HA's UniFi integration creates
the WLAN QR from the controller's SSID/passphrase and invalidates its cached image
when the passphrase changes. There is no need to copy the password into MQTT.

The current Porchlight `wifi` contract still represents a local credential object;
it has not been changed into an HA image URL. The automatic image needs an
authenticated server-side proxy or an HA-native image card, with guest-mode
visibility/freshness gating. Do not embed a long-lived HA credential in browser
JavaScript or expose the HA image's access-token URL in MQTT. Native QR support
does not by itself supply a plaintext password entity for the manual-join label.

## Service restart behavior

`Restart=on-failure` and `RestartSec=10s` apply to automatic failure recovery.
Explicit `systemctl restart` requests do not wait for that recovery delay; normal
systemd start-rate limits still apply. The missing-config condition skips startup;
an existing config with `enabled: false` exits successfully. MQTT reconnects use a
separate 1–30 second backoff. A restart clears in-memory presentation and requires
fresh MQTT plus a new presentation acknowledgement before becoming active.

Repeated restarts on the production appliance have not been tested because the
guest service is not deployed there. Please remove `|| true` from `restart_guest`
before shipping the UI action so restart failures are visible to the setup service,
and coalesce rapid saves if needed. No lifecycle files were changed underneath
your uncommitted action in this handoff.

## Live acceptance and remaining deployment work

- HA package installed, configuration check passed, scripts reloaded after the
  wake timeout was changed to 75 seconds. Vizio's HA coordinator polls every 30
  seconds; the original 30-second wait could falsely time out.
- `Guest Mode` is exposed to Alexa; Assist and Google exposure are off for that
  switch. Spoken discovery/command testing remains outstanding.
- Cold activation at 17:48:50 UTC reported Vizio power on and reached `ui_pending`.
  A repeated ON in the earlier test preserved its session. OFF cancelled the
  chain and cleared requested/status without powering down the TV. The test then
  restored the TV's original off state with a separate explicit cleanup action.
- Backend tests (60), shell checks, staged install/doctor, packaging, and actual
  Mosquitto outage/reconnect smoke passed before UI integration. The fixture test
  now checks all 11 scenarios.
- Calliope currently runs v2.5.0 from the infrastructure workstream. PR #5 is based
  on v2.4.0: reconcile those changes before a full appliance deployment. No backend
  package was installed over that production release.
- Your local docs now describe the screen. Keep the acceptance distinction:
  source implemented, packaged/tested after integration, deployed, and physically
  verified are separate milestones. Full QR scan, TV rendering, and spoken Alexa
  acceptance remain pending.

References: [HA Cast](https://www.home-assistant.io/integrations/cast/),
[HA UniFi images](https://www.home-assistant.io/integrations/unifi/#image),
[HA 2026.9.4 UniFi image implementation](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/unifi/image.py).
