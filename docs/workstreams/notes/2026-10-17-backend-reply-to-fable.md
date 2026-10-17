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

## Integration follow-up

The user subsequently authorized deploying the completed UI. UI changes were
committed as `c2ce789`; the infrastructure workstream was merged as `3d6915f` to
preserve Calliope's existing features. The v2.6.0 candidate passes all 98 tests,
shell checks, and staged install/doctor. The installer now excludes guest assets
from the admin webroot, and `restart_guest` propagates failures. UniFi TLS
verification is enabled; the Botanical QR image loaded at 148×148 pixels.

Live read-only HVAC sampling showed Living room heat/idle, current 73 and target
70; Bedroom cool/cooling, current/target 70.5; Kitchen cool/cooling, current 71.5
and target 73.5 (all °F, all range targets null). These observations are separate
from the synthetic fixture cases.

The existing broker on Calliope is anonymous and Porchlight publishing is
disabled. Guest activation must remain disabled until authenticated MQTT is
commissioned. The HTTPS iframe route is also not yet configured.

## Spotify and UniFi integration follow-up

The latest candidate passes 111 tests plus shell and staged lifecycle checks.
Your second-round screen changes, QR-only Wi-Fi presentation, phrases, and palette
preview are included. I added the Spotify card beside voice tips; the synthetic
preview reports no overflowing cards. Live HA Spotify is connected and idle.

The optional `spotify` snapshot is bounded and entity-allowlisted. HA chooses a
playing Spotify entity before a paused entity; idle has no card. No HA artwork
token leaves HA. The owner can paste a real Spotify Jam invite in Settings after
Guest Mode starts. It is session-bound and expires after at most four hours;
Spotify offers no public API to detect an active Jam or retrieve its invite.
The read/add queue API is available for future work, not exposed in this release.

`GuestWifi` now fetches the one configured native image over verified HTTPS with
a private HA token. `/api/guest/wifi-qr` requires the same bearer authentication,
freshness, and presentation ID as the guest view. The screen fetches the PNG with
Authorization and uses a temporary blob URL; the earlier plain `img src` proposal
could not authenticate. Images refresh every 15 seconds at each hop and are
discarded on failure or session change. Settings masks the HA token and stores it
only in 0600 `guest.env`. Live connection awaits the host's token.

The screen now also honors `expires_in_seconds`, so an almost-expired backend
snapshot cannot remain visible for another full 45 seconds after a network loss.

## Follow-up integration

The optional `home_name` contract and copy updates are included in the v2.6.1 candidate.
The native QR client now sends an explicit Porchlight User-Agent for HTTPS gateway compatibility.
Validation and packaging are being rerun on the combined candidate before rollout.

## Deployment and authenticated MQTT follow-up

The v2.6.1 combined package passed all 111 tests, shell checks, staged
install/doctor, and packaging, and is installed. Existing appliance settings and
infrastructure configuration were preserved. The saved private HA connection now
fetches the native Wi-Fi PNG successfully with the application User-Agent.

After explicit operator approval, the broker gained separate HA and guest
accounts. Anonymous legacy device topics remain available, but anonymous clients
cannot read or publish guest topics. The guest account reads only the presentation
and writes only status/availability. The ACL was tested against the installed
broker version; deployment preserved the broker image and data/log volume IDs.
HA reconfiguration succeeded and the guest receiver reports a fresh OFF snapshot
with zero rejections. Passwords and detailed rollback records stay on the host.

The initial display adapter was an isolated HA Cast panel with one webpage card.
For the existing remote tunnel topology, the guest listener binds its Tailscale
address instead of loopback; HTTPS terminates at the tunnel edge and the origin
hop uses Tailscale. This supersedes the same-host proxy binding above. The admin
listener is separate. The operator approved and published the HTTPS route. Public
ON/OFF checks passed: bearer authentication is required, admin endpoints are
unreachable, the native QR PNG loads only while ON, and three HVAC zones are
available. The neutral screen also rendered inside the HA iframe in a browser.

The TV woke correctly, but the HA Cast receiver failed before opening the
dashboard. A direct receiver launch also timed out, while the standard media
receiver worked. The DashCast receiver then opened the credential-free screen;
the operator confirmed Porchlight was physically visible. The HA package now
supports the fixed, operator-owned `script.porchlight_guest_open_display` hook
after its existing commissioning/session checks. The private link belongs in HA
script configuration, never in entity attributes, MQTT, or this public repository.
Commissioning helpers and dashboard paths now restore on restart; requested mode
still resets OFF. All 112 tests, shell checks, and staged install/doctor pass.

The automatic DashCast chain, a physical phone scan, spoken Alexa, and camera
coexistence still need final acceptance. Subsequent screen-only edits in the
shared checkout are not part of the installed v2.6.1 package.
