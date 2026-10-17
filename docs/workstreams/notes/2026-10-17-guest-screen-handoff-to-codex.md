# Guest screen handoff: Claude → Codex (2026-10-17)

Cross-context note for the agent maintaining the guest backend on
`workstream/guest-mode`. Written by Claude Code, which built the TV screen (G2 in the
original plan) on the same branch while the backend (G1) was being committed.
Both of us edit this checkout; please keep file ownership roughly as below and leave
a reply note in this folder when the asks are done.

## What Claude shipped

| Piece | Files | Notes |
| --- | --- | --- |
| TV kiosk screen | `src/porchlight/webroot/guest/{index.html,guest.css,guest.js}` | 16:9 composition that scales from one unit (`--u`, 1% of frame height) so 720p, 1080p, and 4K render identically. Neutral screen (clock, lamp, host hint) ↔ guest screen (Wi-Fi QR, voice examples, read-only climate) via the View Transitions API, with CSS fallbacks. Time-of-day palettes (morning / afternoon / evening / night). |
| Local QR | `src/porchlight/webroot/guest/vendor/qrcode-generator.js` | Vendored `qrcode-generator@1.4.4` (MIT). The screen encodes your `qr_payload` in byte mode, EC level M, UTF-8. Decoded back to the exact payload with Chrome's BarcodeDetector. |
| Screen server | `src/porchlight/guest_web.py` | `GuestScreenHandler(GuestHandler)` adds an allowlisted static surface (`/guest/`, its css/js/vendor, six font files, two icons) to your JSON handler; everything else still falls through to your 404/401 logic. `GuestScreenServer(GuestHTTPServer)` swaps the handler class. `--preview` serves the screen with synthetic data (no MQTT, no secrets). |
| Service wiring | `src/porchlight/guest_mqtt.py` (one import + one constructor line) | `main()` now builds `GuestScreenServer` instead of `GuestHTTPServer`. `/healthz` therefore reports `ui_available: true`. |
| Dashboard settings | `src/porchlight/guest_settings.py`, `src/porchlight/web.py`, `src/porchlight/webroot/app.js` | The admin Settings view edits `/etc/porchlight/guest.json` (Wi-Fi name/security/password/hidden, welcome, subtitle, voice phrases, climate allowlist, enable flag, token rotation). Every write is validated with **your** `load_guest_config` on a 0600 temp file before `os.replace`, so the dashboard cannot leave a config your service refuses. Responses are masked; a new token is returned once. |
| Restart action | `bin/setup-apply.sh` | New allowlisted `restart_guest` action → `systemctl restart porchlight-guest.service`. The dashboard queues it after each save. |
| Admin isolation | `src/porchlight/web.py`, `src/porchlight/render.py` | The admin listener answers 404 for `/guest`, `/guest/*`, `/api/guest*`; renders skip copying `webroot/guest` into `/var/lib/porchlight/www`. |
| Voice categories | `src/porchlight/guest.py` (two literals), both `guest.json` examples | Added `blinds` alongside `lights` and `music` (max three phrases each). The household's evening routine is "Alexa, close blind 50%." Please keep this when you next touch the validator. |
| Tests | `tests/test_guest_screen.py`, `tests/test_muster_contract.py` | Allowlist, headers, redirect, token/heartbeat round trip, settings writes, admin 404s, synthetic feed stays schema-valid. |

## Contract Claude relies on (please keep stable or tell me)

- `GET /api/guest` → `status` ∈ {`off`,`starting`,`active`,`degraded`,`unavailable`}, `enabled`,
  `session_id`, `expires_in_seconds`, and when enabled: `presentation_id`, `welcome`, `title`,
  `hvac[]`, `alexa{lights,music,blinds}`, `wifi{ssid,security,password,hidden,qr_payload}|null`.
- `POST /api/guest/heartbeat` body exactly `{session_id, presentation_id, visible}`; 400 on
  mismatch; `active` requires an ack within 20 s. The screen polls every 5 s and heartbeats
  after each successful render with `visible: !document.hidden`.
- 401 means the token is wrong: the screen forgets it and shows the neutral "not linked" view.
- Browser-side freshness: 45 s without a successful poll hides the QR and password and blanks
  HVAC even if your process is still up.
- Token transport: the TV opens `http://<GUEST_WEB_HOST>:<GUEST_WEB_PORT>/guest/#t=<token>`.
  The fragment never reaches the server or logs; the page moves it to `sessionStorage` and
  scrubs the URL. No query-string tokens, cookies, or CORS.

## Asks for Codex

1. **HA HVAC payload shape.** Please provide the real `hvac[]` entries your Home Assistant
   package produces, as committed fixtures (for example
   `examples/guest-mode/presentation.<case>.json` or cases inside
   `tests/test_guest_homeassistant.py`) for at least: single setpoint heat; single setpoint
   cool; `heat_cool` range; `off`; `fan_only`/`dry`; an `unavailable` zone; a °C zone with
   0.5-degree steps; and two or more zones at once. State where `label` and `unit` come from
   (friendly name? HA unit system?), the rounding/precision you emit, whether
   `target_temperature` and `target_temperature_low/high` can ever both be set, and the
   maximum zone count you expect in practice. The screen renders 1–8 zones and formats
   temperatures to the nearest 0.5; I will adjust to your fixtures.
2. **Display adapter.** Your doc notes `cast.show_lovelace_view` cannot open an arbitrary URL.
   The screen is a standalone page, so the Alexa-triggered automation needs an adapter that
   can show it: DashCast through the Cast integration (`media_player.play_media` with
   `media_content_type: cast` and a `dashcast` app payload), or a Lovelace `webpage` card in a
   castable view that points at the screen. Both frame the page; the screen allows framing,
   sets no `frame-ancestors`, and works inside an iframe. Both likely require HTTPS for the
   framed URL (mixed content), so please decide whether `porchlight-guest` should terminate
   TLS or sit behind a reverse proxy, and what `GUEST_WEB_HOST` should bind. I can add TLS to
   `GuestScreenServer` once you choose.
3. **Docs you own.** `docs/workstreams/guest-mode.md` still says `/healthz` returns
   `ui_available: false`, that `/guest/` is 404, and that no UI ships; I patched those three
   statements minimally. Please fold the screen into your verification/acceptance sections.
4. **Service restarts.** The dashboard restarts `porchlight-guest.service` after each save
   (`restart_guest`). Confirm `RestartSec`/backoff and the `ConditionPathExists` guard behave
   as you intend under a few quick successive restarts.
5. **Scope.** Claude will keep to the screen, its server module, the dashboard settings form,
   and their tests/docs. Claude will not touch the MQTT adapter, the HA package, presentation
   validation (beyond the `blinds` literal), or lifecycle scripts beyond `restart_guest`.
6. **Wi-Fi precedence (owner decision, 2026-10-17).** The household will also send the guest
   Wi-Fi from Home Assistant, and that takes precedence over the dashboard/`guest.json`
   fields, which become the fallback. Suggested shape, mirroring the config:
   `wifi: {ssid, security: "WPA"|"nopass", password, hidden} | null` inside the presentation
   snapshot, validated exactly like `load_guest_config` validates the local block, counted
   against the 16 KiB cap, held only in memory, and never written to `status.json`, logs, or
   MQTT status. `view()` should prefer a non-null presentation `wifi` over `config["wifi"]`
   and still derive `qr_payload` with `wifi_payload()`. The screen needs no change for this:
   it renders whatever `view.wifi` contains and ignores extra keys, so an optional
   `wifi.source: "home_assistant"|"local"` is welcome for diagnostics. The Settings copy
   already calls its fields the fallback.

## How to look at it

```sh
PYTHONPATH=src python3 -m porchlight.guest_web --preview --port 8766 --scenario cycle
```

Open `http://127.0.0.1:8766/` and follow the link. `?daypart=morning|afternoon|evening|night`
forces a palette. `uv run python -m unittest tests.test_guest_screen` covers the screen.
