# Release

## 2.1.2

- Fixed overview and settings stat cards so the colored status tone is painted
  as a rounded card background instead of a blurred layer that could square off
  or visually escape at the card corners.

## 2.1.1

- Pointed iOS and PWA install metadata at new, dedicated icon filenames so
  devices do not reuse the previously cached `apple-icon.png` or manifest icon
  paths.
- Added a conventional 180px `apple-touch-icon.png` alongside dedicated
  192px/512px PWA icons, all generated as opaque PNGs without alpha.

## 2.1.0

- Fixed installable PWA icons so iOS and browser install surfaces use opaque,
  correctly sized assets without the transparent border intended for the
  dashboard header lamp.
- Kept the header wordmark on one line at medium viewport widths and switched
  to the compact navigation earlier to avoid cramped desktop wrapping.
- Reworded the dashboard's porch-heavy callouts into more direct network and
  LAN posture language.

## 2.0.0

- Added no-SSH appliance onboarding for Raspberry Pi Zero 2 W images with an
  optional first-boot setup access point.
- Added dashboard settings for Home Assistant MQTT broker destination,
  discovery topics, credentials, and test publishing.
- Added constrained JSON setup APIs and file-backed settings writes that mask
  MQTT passwords and preserve unknown config keys.
- Added appliance-mode installer support for NetworkManager, Avahi, setup
  systemd units, and setup completion.

## 1.1.5

- Linked the footer's Muster self-certification statement to the Muster
  framework repository so the certification claim is explainable from the UI.

## 1.1.4

- Added defensive text wrapping for unusually long hostnames in hero headings,
  analysis text, cards, and chip lists so device names cannot force horizontal
  overflow.
- Added the active Porchlight version and GitHub repository link to the footer.

## 1.1.3

- Tightened the animated brand `i` glyph height so the header wordmark does
  not read as a duplicated character at desktop and medium viewport sizes.

## 1.1.2

- Fixed protocol analysis pluralization for one-host and one-service protocol
  detail pages.
- Stabilized featured-host card layout at medium viewport widths so long
  service-chip lists wrap below host identity instead of compressing hostname
  and address text.

## 1.1.1

- Made overview service cards and the environment analysis derive service
  counts from `services.json` when it is present, so the overview cannot show
  zero ports while the protocols view lists indexed services.
- Matched the reference MQTT/RTSP stat separator with the middle dot glyph.

## 1.1.0

- Corrected dashboard display typography to use the reference font weights for
  serif headings, stat values, and the brand mark.
- Made the page body a full-height flex column so sparse routes grow the main
  content area and keep the footer at the bottom of the viewport.

## 1.0.0

- Replaced the minimal generated table dashboard with hosted static assets
  adapted from `azide0x37/porchlight-dashboard`.
- The dashboard now reads the rendered Porchlight JSON sidecars at runtime, so
  the appliance UI updates with each scanner render without needing Node.
- Added dashboard dark mode with system-preference detection, a persistent
  header toggle, and dark-theme CSS tokens.
- Ported the reference dashboard header treatment more faithfully: compact
  icon-only theme controls, header halo/fireflies, hash-route view transitions,
  and a mobile hamburger drawer.
- Vendored the exact deployed Inter, Fraunces, and JetBrains Mono WOFF2 assets
  plus the reference PWA icon set for offline appliance/PWA use.
- Added iOS safe-area metadata, Apple web app metadata, versioned CSS/JS URLs,
  no-store headers for mutable dashboard assets, and mobile 2-column stat tiles.
- Added Muster contract tests that prove the dashboard webroot is packaged and
  backed by `/status.json`, `/hosts.json`, `/services.json`, and
  `/snapshot.json`.

## 0.4.0

- Active scans now run against discovered private hosts instead of blocking on
  broad LAN CIDR size, so a `/22` network can still scan the bounded observed
  host list.
- Added reverse-DNS/PTR name enrichment through `getent hosts`.
- Added service categorization for HTTP, RTSP, MQTT, and common internal ports.
- Added HTTP/HTTPS dashboard links and optional root page title fetching.
- Added Home Assistant sensors for HTTP, RTSP, MQTT, and internal service
  counts.

## 0.3.1

- Fixed scan unit hardening to allow `AF_NETLINK`, which `ip -j
  route/addr/neigh` requires under systemd.

## 0.3.0

- Added the package-backed scanner implementation for config, discovery, Nmap
  XML parsing, SQLite storage, dashboard rendering, health, and web serving.
- Added `porchlight-render`, `porchlight-health`, `porchlight-web`,
  `scan-now.sh`, and `porchlightctl` runtime entrypoints.
- Added systemd timers for discovery, deep scan, render, and health, plus a
  systemd-owned local dashboard service.
- Installer now ships the Python package, scanner/web/health/render entrypoints,
  all systemd units, and apt scanner dependencies (`nmap`, `arp-scan`).
- Doctor now proves SQLite ledger creation, dashboard snapshot rendering, and
  Muster health status output.

## 0.2.0

- Added the first real scanner implementation through `src/porchlight-scan`.
- Added `porchlight-scan.service`, `porchlight-scan.timer`,
  `porchlight-discover.service`, and `porchlight-deep-scan.service`.
- Scanner now writes `/run/porchlight/status.json`, `/run/muster/status.json`,
  and `/var/lib/porchlight/www/*.json` using LAN neighbor and Tailscale data.
- Installer now deploys scanner units and enables the scan timer.

## 0.1.1

- Added apt-based installation for `mosquitto-clients` so real MQTT publishing
  has the configured `mosquitto_pub` adapter available.
- Added a doctor check that fails clearly when `HA_MQTT_ENABLE=1` and the
  configured MQTT publish adapter is missing.

## 0.1.0

- Initial Muster self-certified Porchlight appliance skeleton.
- Added Home Assistant MQTT bridge using mock-first discovery, state, and control artifacts.
- Added versioned install layout under `/opt/porchlight/releases/<version>/`.
- Added `doctor.sh`, `update.sh`, `uninstall.sh`, package generation, and self-certification tests.
