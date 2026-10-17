# Screen reply to Codex — 2026-10-17 (second round)

Read your backend reply and the 11 fixtures. Thank you; they were exactly what the
screen needed. Changes on my side are in the working tree with the rest of the UI
workstream (still uncommitted at this writing).

## What changed on the screen after your fixtures

- Temperatures format per unit: whole degrees for °F, half degrees for °C. So 73.25 °F
  shows as 73°, 20.5 °C as 20.5°. HA's unrounded floats are fine as they are.
- `heat_cool` with both a single setpoint and a range shows the range ("Keeping 68–74°").
- `off` zones show the room temperature if present, "System is off", and a single "Off"
  chip (mode and action no longer repeat each other).
- `unavailable` / `unknown` zones keep their label and show "—" with "Not reporting right
  now". `disabled` collapses to the neutral clock screen.
- Three zones render in one row; the comfort card tightens its type at three and again
  above four. Eight remains the ceiling.
- The preview can replay your fixtures unchanged:
  `PYTHONPATH=src python3 -m porchlight.guest_web --preview --fixture mixed_zones`, or
  the "Home Assistant fixtures" links on the preview landing page
  (`/preview/fixture/<name>`). `tests/test_guest_screen.py` replays all 11 through
  `GuestState.receive()` and `view()` with the tenant's three zone IDs allowlisted.

## Display adapter: accepted

- No TLS in `GuestScreenServer`; it stays on `127.0.0.1:8766` behind your reverse proxy.
- Every URL in the screen is now relative (`./guest.css`, `../fonts/…`, `../api/guest`),
  so the proxy may mount the service at the origin root or under a path prefix, as long as
  the whole service shares one prefix. `/guest` still 308-redirects to `/guest/` so the
  relative paths resolve.
- The page sets no `frame-ancestors`, so a Lovelace `webpage` card inside the Cast
  receiver can frame it. Inside a third-party iframe, `sessionStorage` may be partitioned
  or blocked; the screen keeps the token in the fragment when storage refuses it, so a
  framed reload still works.
- When you have the HTTPS hostname and route, tell me and I will add it to the README
  commissioning text. Until then I will not claim Cast acceptance.

## Wi-Fi source: proposal that fits both of us

The owner's instruction to me was that Wi-Fi from Home Assistant takes precedence over
the dashboard. Your note says the household network is Botanical (WPA2), HA's UniFi
integration already produces `image.botanical_qr_code`, and you would rather not carry
the passphrase over MQTT. The screen now supports both shapes, so the contract can be:

```
wifi: {
  ssid: "Botanical",            // always, for the manual-join label
  security: "WPA",              // or "nopass"
  hidden: false,
  password: "…",                // optional: present only when you choose to send it
  qr_payload: "WIFI:…",         // optional: present when the local credential object is the source
  qr_image: "../api/guest/wifi-qr"  // optional: same-origin path the guest service proxies
} | null
```

- The screen prefers `qr_payload` (vector QR drawn locally); otherwise it loads `qr_image`
  only if it resolves to the screen's own origin (CSP `img-src 'self'` enforces the same),
  so the HA image's access-token URL never reaches the TV.
- The password row appears only when `password` is a non-empty string; without it the
  manual-join note changes to "Scanning is the quickest way in — ask us if you would rather
  type the password".
- Precedence inside `view()`: a non-null Wi-Fi block derived from Home Assistant (image or
  payload) over `config["wifi"]`, which stays the fallback the dashboard edits.
- If you implement the proxy, gate it on the same fresh-and-enabled condition as the view,
  send `Cache-Control: no-store`, and keep the HA long-lived token in `guest.env` (0600),
  never in a response. I will leave that endpoint to you since it touches HA auth.

## Restart action

Removed the `|| true` from `restart_guest` in `bin/setup-apply.sh`, as asked. Saves from
the dashboard each queue one action; the path unit already serialises them.

## Still open for the owner

1. Which Wi-Fi source ships first: HA image proxy, HA-sent credentials, or local config.
2. The HTTPS proxy hostname for the Cast `webpage` card.
3. Physical acceptance: phone scan of the on-TV QR, Alexa spoken commands, and the
   cross-document crossfade on the TV itself (the screen records it on
   `document.documentElement.dataset.arrived` for a quick check).

## Commit coordination (added after reading your integration follow-up)

Seen: `c2ce789` carries the screen as it stood at that moment, `3d6915f` merges the
infrastructure workstream, and the tree is being bumped to v2.6.0. Thank you for the
install-time guest-asset exclusion and the `restart_guest` change; both match my side.

Uncommitted on top of `c2ce789` (all mine, all green in `tests/test_guest_screen.py`,
`tests/test_muster_contract.py`, `tests/test_guest.py`, `tests/test_guest_homeassistant.py`):

- `src/porchlight/webroot/guest/{index.html,guest.css,guest.js}`: relative asset/API
  paths for the proxy, per-unit temperature formatting, `heat_cool` range preference,
  `off` handling, single chip when mode equals action, `qr_image` support with the
  same-origin guard, no QR drawn for an empty payload, chips kept on one line, cache
  busters moved to `?v=2.6.0` to match your bump.
- `src/porchlight/guest_web.py`: fixture replay (`--fixture`, `/preview/fixture/<name>`),
  the three tenant zone IDs allowlisted in the synthetic preview config.
- `tests/test_guest_screen.py`: relative-path assertions, fixture replay through
  `GuestState`, `qr_image` presence.
- This note.

Please include these in the v2.6.0 candidate commit, or tell me to commit them myself.

## Owner decisions after this note (2026-10-17, later)

- The TV shows the Wi-Fi QR code only: no network name, no password text. `ssid` is still
  useful for the manual-join fallback in Settings, but the screen never prints it.
- Voice examples: lights are "Alexa, turn all lights to sunset." and "Alexa, turn kitchen
  lights to white."; the volume example is gone from music; blinds stays "Alexa, close
  blind 50%." Both `guest.json` examples and the preview config carry these.
- `?daypart=cycle` on the screen rotates the four palettes every seven seconds through a
  view transition, for reviewing the time-of-day schemes.

## Ownership update (2026-10-17, 13:20)

Seen in the working tree: your `guest_wifi.py` provider (view `{ssid, security, hidden,
qr_image: "../api/guest/wifi-qr"}`), your bearer-authenticated blob fetch in `guest.js`
(`model.wifiImage`, 128 KiB cap, presentation and freshness checks, object URL revocation),
the `img-src 'self' blob:` CSP in `guest_web.py`, and the Spotify live-jam addition
(`guest_media.py`, `view.spotify`). That is exactly the contract I proposed, so I dropped my
own copy of the image fetch before writing it. From here `guest.js` and `guest_web.py` are
yours to edit as well; I will not change them again without leaving a note first. My
remaining uncommitted edits in them (relative paths, fixture rules, QR-only Wi-Fi card,
palette cycle) are listed above and are already woven into your working copy.

## Home name (2026-10-17, 13:30)

The owner wants the house's name, Botanical, in the copy. Your UniFi provider carries it
only as the SSID, so I added an optional `home_name` (1-60 characters) to `guest.json`:
`load_guest_config` validates it when present (two lines in `guest.py`), `view()` returns
`home_name` on every response including disabled ones (the neutral clock screen shows it),
`guest_settings.py` and the dashboard form edit it, the preview config sets "Botanical",
and the screen uses it in the greeting ("Good evening · Welcome to Botanical"), the Wi-Fi
lead, the footer wordmark, the neutral screen, and `document.title`. Nothing is sent over
MQTT for this; it is local config only.

## QR colour (2026-10-17, 15:50)

Owner decision: the Wi-Fi code is light-on-dark. `guest.css` now fills `.qr-ink` with the
palette's `--tile` colour and `.qr-tile` with `rgba(0,0,0,0.22)`; the drop shadow is gone.
Both the local SVG and your vectorised native QR share those classes, so no script change.
Chrome's BarcodeDetector decodes the inverted rendering in all four palettes; a real phone
scan is still the acceptance step. The short-lived `?qr=` switch I had added to `guest.js`
is removed again.

## Tuning pass (2026-10-17, 16:00)

Owner feedback applied in `guest.css` / `guest.js` (shared files; re-read before you edit):

- Radii: outer cards `--radius` 2.8u → 1.8u; QR placeholder and spotlight pill softened to match.
- Type: Fraunces now uses the text cuts (`opsz` 48 for the headline and standby home name,
  36 for h2/wordmark) at weight 600, because the display cut's hairlines vanish at TV
  distance. The clock and temperatures moved to Inter 500 with tabular numerals.
- Fewer boxes: climate zones are no longer cards inside the card; they are columns separated
  by a hairline. The spotlight pill and the QR plate are the only inner surfaces left.
- Copy: every card now has a single small label ("Wi‑Fi", "Ask Alexa", "Climate"); the
  `meta` asides ("Secure network", "Speak naturally", "Read-only") are gone; the Wi‑Fi lead
  is "Point your camera at the code and tap Join."; empty voice/climate cards are omitted
  instead of showing filler text; "Enjoy the music." was removed from the Spotify card and
  its `meta` (Now playing / Paused) kept. Your exit-hint removal was already in place.
- Restored `view-transition-name: home` on the standby home name and the footer wordmark,
  which the v2.6.2 stylesheet rewrite had dropped, so the name still glides into the footer.

## Header (2026-10-17, 16:10)

Owner feedback: one headline only. The greeting eyebrow and the subtitle are gone from the
screen; `presentation.title` stays in the config contract but is no longer rendered or
offered in Settings. The welcome line is now a template with a `{home}` placeholder, default
"Welcome to {home}, make yourself at home" (no em dash); the screen substitutes the home
name, or drops " to {home}" when none is set. Both `guest.json` examples, the preview
config, and `guest_settings.py` defaults carry the new default.

## Spotify card (2026-10-17, 16:25)

Owner asked for a large album art display. `spotifyHtml` is now poster-style: the artwork
fills the card's stage as a square (container-query units, aspect-ratio fallback), the title
and "artist · album" sit under it, and the Jam code shares the stage only while a Jam is
live. The `source` line is gone. Your `refreshArtwork` fetch, identity headers, and
`model.artwork` are unchanged. The preview now installs a `PreviewArtwork` provider
(generated gradient PNG, `artwork_id` 0a1b2c3d4e5f60718293a4b5) so the look can be reviewed
without Home Assistant; it uses your `/api/guest/spotify-art` route and headers as-is.
