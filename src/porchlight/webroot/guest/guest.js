/* Porchlight guest screen. A kiosk page for the living-room TV: it reads the restricted guest
   view, draws the Wi-Fi QR locally, keeps a presenter heartbeat, and fails closed when the
   house stops talking to it. All visible state changes go through the View Transitions API
   when the browser has it; otherwise the same DOM swap happens without animation. */
(() => {
  "use strict";

  const POLL_MS = 5000;
  const STALE_MS = 45000;
  const REQUEST_TIMEOUT_MS = 4000;
  const SPOTLIGHT_MS = 8000;
  const DRIFT_MS = 10 * 60 * 1000;
  const REFRESH_HOUR = 4;
  const TOKEN_KEY = "porchlight-guest-token";
  const SCREEN_VERSION = new URL(document.currentScript.src).searchParams.get("v") || "unknown";

  const stage = document.getElementById("stage");
  const root = document.documentElement;
  const reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  // ---------------------------------------------------------------------------
  // Access link. Home Assistant opens /guest/#t=<token>. The fragment never reaches the
  // server or its logs; we move it into session storage and scrub it from the address bar.
  // ---------------------------------------------------------------------------
  function readToken() {
    let token = "";
    const match = /(?:^|[#&])t=([A-Za-z0-9_-]{32,128})(?:&|$)/.exec(window.location.hash || "");
    if (match) {
      token = match[1];
      let stored = false;
      try {
        window.sessionStorage.setItem(TOKEN_KEY, token);
        stored = window.sessionStorage.getItem(TOKEN_KEY) === token;
      } catch (_) { stored = false; }
      if (stored) {
        try { window.history.replaceState(null, "", window.location.pathname + window.location.search); } catch (_) { /* ignore */ }
      }
    } else {
      try { token = window.sessionStorage.getItem(TOKEN_KEY) || ""; } catch (_) { token = ""; }
    }
    return token;
  }

  const model = {
    token: readToken(),
    view: null,
    lastGoodAt: 0,
    error: null,
    ack: null,
    key: "",
    spot: -1,
    loadedAt: Date.now(),
    transitioning: false,
    wifiImage: null,
    artwork: null,
  };

  // ---------------------------------------------------------------------------
  // Copy and formatting
  // ---------------------------------------------------------------------------
  const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  const longDateFormat = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" });
  const shortDateFormat = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" });

  const ACTION_LABEL = {
    off: "Off",
    heating: "Heating now",
    cooling: "Cooling now",
    drying: "Drying",
    idle: "Holding steady",
    fan: "Fan running",
    preheating: "Warming up",
    defrosting: "Defrosting",
  };
  // The TV only reaches this page once Home Assistant has turned guest mode on, so there is
  // no "off" screen to design. Before the first presentation lands, and for the moment after
  // guest mode ends, the page shows only the lamp and the home name; the notes below are the
  // two diagnostics worth a line of text.
  const NOTES = {
    unavailable: "Catching up with the house\u2026",
    unlinked: "This screen isn\u2019t linked yet. Open it from Home Assistant\u2019s guest link.",
  };

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // The palette follows the household's day: dawn-tinted mornings, sunlit afternoons, the
  // lamplit evening, and a dimmer, cooler late night. ?daypart=night forces one for review.
  const DAYPARTS = ["morning", "afternoon", "evening", "night"];
  const DAYPART_OVERRIDE = (/[?&]daypart=(morning|afternoon|evening|night|cycle)/.exec(window.location.search) || [])[1] || "";
  const DAYPART_CYCLE_MS = 7000;
  let cycleIndex = 0;
  function daypart(date) {
    if (DAYPART_OVERRIDE === "cycle") return DAYPARTS[cycleIndex % DAYPARTS.length];
    if (DAYPART_OVERRIDE) return DAYPART_OVERRIDE;
    const hour = date.getHours();
    if (hour >= 5 && hour < 11) return "morning";
    if (hour >= 11 && hour < 17) return "afternoon";
    if (hour >= 17 && hour < 22) return "evening";
    return "night";
  }


  function applyDaypart(animate) {
    const next = daypart(new Date());
    if (root.dataset.daypart === next) return;
    if (!animate || !root.dataset.daypart) {
      root.dataset.daypart = next;
      return;
    }
    transition(() => { root.dataset.daypart = next; });
  }

  // Home Assistant passes thermostat floats through unrounded (73.25 is real). Guests read
  // whole degrees Fahrenheit and half degrees Celsius, matching the thermostats themselves.
  function formatTemp(value, unit) {
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    const step = unit === "\u00b0C" ? 0.5 : 1;
    const rounded = Math.round(value / step) * step;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  }

  function lengthClass(text, long, xlong) {
    const size = String(text || "").length;
    if (size > xlong) return "xlong";
    if (size > long) return "long";
    return "short";
  }

  // "Alexa, play jazz" -> wake word highlighted, surrounding quotes normalised.
  function phraseHtml(text) {
    const clean = String(text || "").trim().replace(/^[“"']+|[”"']+$/g, "");
    const comma = clean.indexOf(",");
    if (comma > 0 && comma < 12) {
      return `<em class="wake">${esc(clean.slice(0, comma + 1))}</em>${esc(clean.slice(comma + 1))}`;
    }
    return esc(clean);
  }

  const ICONS = {
    bulb: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1.1 1.3 1.1 2.2h5c0-.9.5-1.7 1.1-2.2A6 6 0 0 0 12 3z"/></svg>',
    note: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/></svg>',
    blind: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M4 7.5h16M4 12h16M4 16.5h16M12 16.5v4.5"/></svg>',
  };

  // A QR image is only ever loaded from this origin (the guest service proxies it); anything
  // else is ignored so a payload can never point the TV at another host.
  function sameOriginImage(value) {
    if (typeof value !== "string" || !value) return "";
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin ? url.pathname + url.search : "";
    } catch (_) {
      return "";
    }
  }

  // ---------------------------------------------------------------------------
  // Wi-Fi QR, drawn locally from the server's WIFI: payload. The white tile and quiet zone
  // live inside the SVG so the code always stays square and contained in its stage.
  // ---------------------------------------------------------------------------
  function qrSvg(payload, label = "Wi-Fi join code") {
    if (typeof window.qrcode !== "function") return "";
    try {
      if (window.qrcode.stringToBytesFuncs && window.qrcode.stringToBytesFuncs["UTF-8"]) {
        window.qrcode.stringToBytes = window.qrcode.stringToBytesFuncs["UTF-8"];
      }
      const code = window.qrcode(0, "M");
      code.addData(payload, "Byte");
      code.make();
      const n = code.getModuleCount();
      const quiet = 4;
      let d = "";
      for (let r = 0; r < n; r += 1) {
        let c = 0;
        while (c < n) {
          if (!code.isDark(r, c)) { c += 1; continue; }
          let run = 1;
          while (c + run < n && code.isDark(r, c + run)) run += 1;
          d += `M${c} ${r}h${run}v1h-${run}z`;
          c += run;
        }
      }
      const size = n + quiet * 2;
      return `<svg viewBox="${-quiet} ${-quiet} ${size} ${size}" role="img" aria-label="${esc(label)}">`
        + `<rect class="qr-tile" x="${-quiet}" y="${-quiet}" width="${size}" height="${size}" rx="2.4"/>`
        + `<path class="qr-ink" d="${d}"/></svg>`;
    } catch (_) {
      return "";
    }
  }

  function qrImageSvg(image) {
    // The helper supplies bounded numeric geometry, never source markup. Keep every
    // source pixel, including its quiet zone, in the same coordinate space.
    return `<svg width="${image.width}" height="${image.height}" viewBox="0 0 ${image.width} ${image.height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Wi-Fi join code">`
      + `<rect class="qr-tile" width="${image.width}" height="${image.height}"/>`
      + `<path class="qr-ink" d="${image.path}"/></svg>`;
  }

  // ---------------------------------------------------------------------------
  // Views
  // ---------------------------------------------------------------------------
  function clockHtml(date, variant) {
    const dateText = variant === "neutral" ? longDateFormat.format(date) : shortDateFormat.format(date);
    return `<p class="clock">${esc(timeFormat.format(date))}</p><p class="date">${esc(dateText)}</p>`;
  }

  function statusPill() {
    const fresh = freshView();
    if (!model.token) return `<p class="status-pill" data-tone="idle">Not linked</p>`;
    if (!fresh || (model.view && model.view.status === "unavailable")) return `<p class="status-pill" data-tone="stale">Reconnecting\u2026</p>`;
    if (model.view && model.view.enabled) {
      if (model.ack === "active") return `<p class="status-pill" data-tone="live">Live</p>`;
      return `<p class="status-pill" data-tone="sync">Syncing</p>`;
    }
    return "";
  }

  // The household's name, when the owner has set one in Settings. It travels with every
  // view, including the neutral one, so the clock screen can carry it too.
  function homeName() {
    return model.view && typeof model.view.home_name === "string" ? model.view.home_name.trim() : "";
  }

  // The welcome line comes from Settings and may carry a {home} placeholder. Without a home
  // name the placeholder and its preposition fall away: "Welcome, make yourself at home".
  function welcomeText(view) {
    const raw = String(view.welcome || "Welcome to {home}, make yourself at home");
    const home = homeName();
    if (home) return raw.replace(/\{home\}/g, home);
    return raw.replace(/\s+(to|at|in)\s+\{home\}/g, "").replace(/\{home\}/g, "").replace(/\s{2,}/g, " ").trim();
  }

  function neutralView(reason) {
    const note = NOTES[reason] || "";
    const home = homeName();
    return `<section class="neutral" data-view="${esc(reason)}">
      <div class="lamp"><img src="../icon-round.png" alt=""></div>
      ${home ? `<p class="home-name">${esc(home)}</p>` : ""}
      ${note ? `<p class="hint">${note}</p>` : ""}
      ${statusPill()}
    </section>`;
  }

  function wifiHtml(view, stale) {
    const wifi = view.wifi;
    if (!wifi) {
      return `<section class="card wifi">
        <div class="card-head"><p class="eyebrow">Wi\u2011Fi</p></div>
        <div class="qr-stage"><div class="qr-placeholder">No guest network is set up on this screen yet.</div></div>
      </section>`;
    }
    const open = wifi.security === "nopass";
    const svg = stale || typeof wifi.qr_payload !== "string" || !wifi.qr_payload ? "" : qrSvg(wifi.qr_payload);
    const image = !stale && !svg && model.wifiImage && model.wifiImage.presentation === view.presentation_id
      && model.wifiImage.session === view.session_id ? model.wifiImage.svg : "";
    let stageHtml;
    if (stale) stageHtml = `<div class="qr-placeholder">Wi\u2011Fi details will be back in a moment.</div>`;
    else if (svg) stageHtml = svg;
    else if (image) stageHtml = image;
    else stageHtml = `<div class="qr-placeholder">Ask us for the Wi\u2011Fi \u2014 the code is on its way.</div>`;
    let lead;
    if (stale) lead = `<p class="lead">Reconnecting to the house.</p>`;
    else if (open) lead = `<p class="lead">Point your camera at the code \u2014 no password needed.</p>`;
    else lead = `<p class="lead">Point your camera at the code and tap <strong>Join</strong>.</p>`;
    // By the household's choice the network name and password never appear on the TV.
    return `<section class="card wifi">
      <div class="card-head"><p class="eyebrow">Wi\u2011Fi</p></div>
      <div class="qr-stage">${stageHtml}</div>
      ${lead}
    </section>`;
  }

  function groupHtml(label, icon, phrases) {
    if (!Array.isArray(phrases) || !phrases.length) return "";
    const items = phrases.slice(0, 3).map((phrase) => `<li class="phrase"><span class="spot" aria-hidden="true"></span><span class="text">“${phraseHtml(phrase)}”</span></li>`).join("");
    return `<div class="group"><h3>${icon}${esc(label)}</h3><ul class="phrases">${items}</ul></div>`;
  }

  function voiceHtml(view, withSpotify = false) {
    const alexa = view.alexa || {};
    const groups = groupHtml("Lights", ICONS.bulb, alexa.lights) + (withSpotify ? "" : groupHtml("Music", ICONS.note, alexa.music)) + groupHtml("Blinds", ICONS.blind, alexa.blinds);
    if (!groups) return "";
    const count = ["lights", "music", "blinds"].reduce((total, key) => total + Math.min(3, (alexa[key] || []).length), 0);
    return `<section class="card voice" data-phrases="${count}">
      <div class="card-head"><p class="eyebrow">Ask Alexa</p></div>
      <div class="groups">${groups}</div>
    </section>`;
  }

  function zoneHtml(zone, index, stale) {
    const available = !stale && zone.available;
    const unit = zone.unit === "°C" ? "C" : "F";
    const current = available ? formatTemp(zone.current_temperature, zone.unit) : null;
    const low = available ? formatTemp(zone.target_temperature_low, zone.unit) : null;
    const high = available ? formatTemp(zone.target_temperature_high, zone.unit) : null;
    const target = available ? formatTemp(zone.target_temperature, zone.unit) : null;
    let detail = "";
    // Some integrations publish a single setpoint alongside the range; the range wins in auto.
    if (low && high) detail = `<span class="target">Keeping ${esc(low)}\u2013${esc(high)}\u00b0</span>`;
    else if (target && zone.mode !== "off") detail = `<span class="target">Set to ${esc(target)}\u00b0</span>`;
    else if (available && zone.mode === "off") detail = `<span>System is off</span>`;
    let chip = "";
    const actionLabel = ACTION_LABEL[zone.action];
    if (available && actionLabel) {
      chip = `<span class="chip" data-action="${esc(zone.action)}">${esc(actionLabel)}</span>`;
    }
    if (!available) detail = `<span>${stale ? "Catching up\u2026" : "Not reporting right now"}</span>`;
    const temp = current == null
      ? `<p class="zone-temp is-blank" data-zone="${index}">—</p>`
      : `<p class="zone-temp" data-zone="${index}">${esc(current)}°<sup>${unit}</sup></p>`;
    return `<article class="zone">${temp}<p class="zone-label">${esc(zone.label || "Climate")}</p><p class="zone-detail">${detail}${chip}</p></article>`;
  }

  function comfortHtml(view, stale) {
    const zones = Array.isArray(view.hvac) ? view.hvac.slice(0, 8) : [];
    if (!zones.length) return "";
    return `<section class="card comfort" data-zones="${zones.length}">
      <div class="card-head"><p class="eyebrow">Climate</p></div>
      <div class="zones">${zones.map((zone, index) => zoneHtml(zone, index, stale)).join("")}</div>
    </section>`;
  }

  function guestView(view, stale) {
    const now = new Date();
    const spotify = !stale && view.spotify;
    const home = homeName();
    return `<section class="guest" data-view="${stale ? "stale" : "active"}">
      ${wifiHtml(view, stale)}
      <div class="main">
        <header class="welcome">
          <h1 class="headline">${esc(welcomeText(view))}</h1>
        </header>
        <div class="social-row${spotify ? " has-spotify" : ""}">
          ${voiceHtml(view, !!spotify)}
          ${spotify ? spotifyHtml(spotify) : ""}
        </div>
        ${comfortHtml(view, stale)}
      </div>
      <footer class="foot">
        <div class="brand"><div class="lamp"><img src="../icon-round.png" alt=""></div><p class="wordmark">${home ? `${esc(home)} <span class="credit">\u00b7 Porchlight</span>` : "Porchlight"}</p></div>
        ${statusPill()}
        <div class="time">${clockHtml(now, "guest")}</div>
      </footer>
    </section>`;
  }

  function liveJam(spotify) {
    const jam = spotify && spotify.jam;
    return jam && Date.parse(jam.expires_at) > Date.now() ? jam : null;
  }

  function spotifyHtml(spotify) {
    const jam = liveJam(spotify);
    const artwork = model.artwork && model.artwork.id === spotify.artwork_id ? model.artwork.url : "";
    const art = artwork
      ? `<img class="album-art" src="${esc(artwork)}" alt="Album cover">`
      : `<div class="album-art album-art-empty" aria-hidden="true">${ICONS.note}</div>`;
    const credit = [spotify.artist, spotify.album].filter(Boolean).join(" \u00b7 ");
    return `<section class="card spotify${jam ? " has-jam" : ""}">
      <div class="card-head"><p class="eyebrow">Spotify</p><p class="meta">${spotify.state === "playing" ? "Now playing" : "Paused"}</p></div>
      <div class="art-stage">${art}${jam ? `<div class="jam"><div class="jam-qr">${qrSvg(jam.url, "Join the Spotify Jam")}</div><p class="jam-label">Scan to join the Jam</p></div>` : ""}</div>
      <div class="track-copy"><h2 class="track-title">${esc(spotify.title)}</h2>
        ${credit ? `<p class="track-artist">${esc(credit)}</p>` : ""}</div>
    </section>`;
  }

  // ---------------------------------------------------------------------------
  // State derivation. The browser enforces freshness on its own clock as well: if the
  // view has not been refreshed within STALE_MS the credentials leave the screen.
  // ---------------------------------------------------------------------------
  function derive() {
    if (!model.token) return { screen: "neutral", reason: "unlinked" };
    const view = model.view;
    const fresh = freshView();
    if (!view) return { screen: "neutral", reason: model.error ? "unavailable" : "standby" };
    if (!view.enabled) return { screen: "neutral", reason: fresh && view.status === "off" ? "standby" : "unavailable" };
    return { screen: "guest", stale: !fresh };
  }

  function freshView() {
    const view = model.view;
    if (!view) return false;
    const remaining = typeof view.expires_in_seconds === "number" ? view.expires_in_seconds * 1000 : STALE_MS;
    return Date.now() - model.lastGoodAt < Math.min(STALE_MS, Math.max(0, remaining));
  }

  function renderKey(state) {
    const view = model.view || {};
    const significant = state.screen === "guest"
      ? [view.session_id, view.presentation_id, view.welcome, view.title, view.wifi, model.wifiImage && model.wifiImage.svg, model.artwork && model.artwork.url, view.alexa, view.spotify, !!liveJam(view.spotify),
         (view.hvac || []).map((zone) => [zone.id, zone.label, zone.available, zone.unit, zone.mode, zone.action,
           formatTemp(zone.current_temperature, zone.unit), formatTemp(zone.target_temperature, zone.unit),
           formatTemp(zone.target_temperature_low, zone.unit), formatTemp(zone.target_temperature_high, zone.unit)])]
      : [];
    return JSON.stringify([state.screen, state.reason || "", !!state.stale, model.ack, !model.token, homeName(), significant]);
  }

  function transition(run) {
    if (reduceMotion || document.hidden || typeof document.startViewTransition !== "function") {
      run();
      return Promise.resolve();
    }
    model.transitioning = true;
    let vt;
    try {
      vt = document.startViewTransition(run);
    } catch (_) {
      model.transitioning = false;
      run();
      return Promise.resolve();
    }
    // A transition that starts while another is mid-flight skips the older one; that is
    // expected here, so swallow the rejections instead of surfacing them as page errors.
    const quiet = () => undefined;
    vt.ready.catch(quiet);
    vt.updateCallbackDone.catch(quiet);
    return vt.finished.catch(quiet).finally(() => { model.transitioning = false; });
  }

  function afterPaint(state) {
    root.dataset.screen = state.screen === "guest" ? (state.stale ? "stale" : "guest") : "neutral";
    const home = homeName();
    document.title = home ? `${home} \u00b7 Hosting Guests` : "Porchlight - Hosting Guests";
    const phrases = stage.querySelectorAll(".phrase");
    if (phrases.length) {
      if (model.spot < 0 || model.spot >= phrases.length) model.spot = 0;
      phrases[model.spot].classList.add("is-spot");
    }
    stage.querySelectorAll(".zone-temp").forEach((element) => {
      element.style.setProperty("view-transition-name", `zone-temp-${element.dataset.zone}`);
    });
  }

  function render(force) {
    const state = derive();
    if (state.screen !== "guest" || state.stale) { clearWifiImage(); clearArtwork(); }
    const key = renderKey(state);
    if (!force && key === model.key) {
      tickClock();
      return Promise.resolve();
    }
    model.key = key;
    const html = state.screen === "guest" ? guestView(model.view, state.stale) : neutralView(state.reason);
    return transition(() => {
      stage.innerHTML = html;
      afterPaint(state);
    });
  }

  // ---------------------------------------------------------------------------
  // Clock: plain text updates on the minute, never through a transition.
  // ---------------------------------------------------------------------------
  function tickClock() {
    applyDaypart(true);
    const now = new Date();
    const clock = stage.querySelector(".clock");
    const date = stage.querySelector(".date");
    if (clock) clock.textContent = timeFormat.format(now);
    if (date) date.textContent = (stage.querySelector(".neutral") ? longDateFormat : shortDateFormat).format(now);
  }

  function scheduleClock() {
    const now = new Date();
    const delay = (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 20;
    window.setTimeout(() => {
      tickClock();
      maybeNightlyRefresh();
      scheduleClock();
    }, Math.max(250, delay));
  }

  // A kiosk page runs for weeks. One quiet reload a night keeps memory and assets honest;
  // it is a same-origin navigation, so the cross-document view transition crossfades it.
  function maybeNightlyRefresh() {
    const now = new Date();
    if (now.getHours() !== REFRESH_HOUR || now.getMinutes() !== 0) return;
    if (Date.now() - model.loadedAt < 60 * 60 * 1000) return;
    window.location.replace(window.location.pathname + window.location.search);
  }

  // ---------------------------------------------------------------------------
  // Network
  // ---------------------------------------------------------------------------
  function request(method, path, body) {
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller ? window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS) : null;
    const headers = { Authorization: `Bearer ${model.token}` };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    return fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      signal: controller ? controller.signal : undefined,
    }).finally(() => { if (timer) window.clearTimeout(timer); });
  }

  let polling = false;
  let wifiImageGeneration = 0;
  function clearWifiImage() {
    wifiImageGeneration += 1;
    model.wifiImage = null;
  }

  async function refreshWifiImage(view) {
    const path = view.enabled && view.wifi && sameOriginImage(view.wifi.qr_image);
    // Only the one protected image endpoint is allowed; never put a token in an img URL.
    if (!path || path !== new URL("../api/guest/wifi-qr", window.location.href).pathname) {
      clearWifiImage();
      return;
    }
    if (model.wifiImage && model.wifiImage.presentation === view.presentation_id
        && model.wifiImage.session === view.session_id && Date.now() - model.wifiImage.at < 15000) return;
    clearWifiImage();
    const generation = wifiImageGeneration;
    const current = () => generation === wifiImageGeneration && model.token && freshView()
      && model.view.enabled && model.view.presentation_id === view.presentation_id && model.view.session_id === view.session_id;
    try {
      if (!window.PorchlightQrImage || !current()) throw new Error("wifi unavailable");
      const response = await request("GET", path);
      if (!response.ok || response.headers.get("Content-Type") !== "image/png" || response.headers.get("X-Porchlight-Presentation") !== view.presentation_id) throw new Error("wifi unavailable");
      const blob = await response.blob();
      if (!current()) throw new Error("wifi expired");
      const image = await window.PorchlightQrImage.fromBlob(blob);
      if (!current()) throw new Error("wifi expired");
      model.wifiImage = { svg: qrImageSvg(image), presentation: view.presentation_id, session: view.session_id, at: Date.now() };
    } catch (_) { if (generation === wifiImageGeneration) clearWifiImage(); }
  }

  let artworkGeneration = 0;
  function clearArtwork() {
    artworkGeneration += 1;
    if (model.artwork) URL.revokeObjectURL(model.artwork.url);
    model.artwork = null;
  }

  async function refreshArtwork(view) {
    const song = view.enabled && view.spotify;
    const path = song && sameOriginImage(song.artwork_image);
    if (!path || path !== new URL("../api/guest/spotify-art", window.location.href).pathname
        || !/^[a-f0-9]{24}$/.test(song.artwork_id || "")) {
      clearArtwork();
      return;
    }
    if (model.artwork && model.artwork.id === song.artwork_id && model.artwork.presentation === view.presentation_id) return;
    clearArtwork();
    const generation = artworkGeneration;
    const current = () => generation === artworkGeneration && model.token && freshView()
      && model.view.enabled && model.view.presentation_id === view.presentation_id
      && model.view.spotify && model.view.spotify.artwork_id === song.artwork_id;
    let url = "";
    let image;
    let timer;
    try {
      const response = await request("GET", path);
      if (!response.ok || !["image/jpeg", "image/png"].includes(response.headers.get("Content-Type"))
          || response.headers.get("X-Porchlight-Presentation") !== view.presentation_id
          || response.headers.get("X-Porchlight-Artwork") !== song.artwork_id) throw new Error("artwork unavailable");
      const blob = await response.blob();
      if (!current() || !blob.size || blob.size > 512 * 1024) throw new Error("artwork expired");
      url = URL.createObjectURL(blob);
      image = new Image();
      await new Promise((resolve, reject) => {
        timer = window.setTimeout(() => reject(new Error("artwork timeout")), REQUEST_TIMEOUT_MS);
        image.onload = resolve;
        image.onerror = () => reject(new Error("artwork decode"));
        image.src = url;
      });
      if (!current() || image.naturalWidth > 2048 || image.naturalHeight > 2048) throw new Error("artwork expired");
      model.artwork = { url, id: song.artwork_id, presentation: view.presentation_id };
      url = "";
    } catch (_) { if (generation === artworkGeneration) clearArtwork(); }
    finally {
      if (timer) window.clearTimeout(timer);
      if (image) { image.onload = image.onerror = null; image.removeAttribute("src"); }
      if (url) URL.revokeObjectURL(url);
    }
  }

  async function poll() {
    if (polling || !model.token) return;
    polling = true;
    try {
      const response = await request("GET", "../api/guest");
      if (response.status === 401) {
        model.token = "";
        try { window.sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* ignore */ }
        model.view = null;
        model.error = "unauthorized";
        return;
      }
      if (!response.ok) throw new Error(`guest view ${response.status}`);
      const view = await response.json();
      model.view = view;
      model.lastGoodAt = Date.now();
      model.error = null;
      await Promise.all([refreshWifiImage(view), refreshArtwork(view)]);
      await render(false);
      if (view.enabled && view.session_id && view.presentation_id) {
        if (!document.hidden) await new Promise((resolve) => window.requestAnimationFrame(resolve));
        if (freshView() && model.view.presentation_id === view.presentation_id) await heartbeat(view);
      } else {
        model.ack = null;
      }
    } catch (error) {
      model.error = String(error && error.message || error);
    } finally {
      polling = false;
      render(false);
    }
  }

  function displayMetrics() {
    const qr = stage.querySelector(".wifi .qr-tile, .wifi .qr-image");
    const bounds = qr && qr.getBoundingClientRect();
    const overflow = [];
    ["welcome", "voice", "comfort", "spotify", "foot", "zone", "wifi", "qr-stage"].forEach((name) => {
      const selector = name === "zone" ? ".zone, .zone-detail, .chip" : "." + name;
      if (Array.from(stage.querySelectorAll(selector)).some((el) => el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2)) overflow.push(name);
    });
    const supports = (property, value) => !!(window.CSS && CSS.supports && CSS.supports(property, value));
    return {
      version: SCREEN_VERSION,
      viewport_width: Math.round(window.innerWidth), viewport_height: Math.round(window.innerHeight),
      pixel_ratio: window.devicePixelRatio || 1,
      font_px: Math.round(parseFloat(getComputedStyle(root).fontSize) * 100) / 100,
      overflow_width: Math.max(0, root.scrollWidth - window.innerWidth),
      overflow_height: Math.max(0, root.scrollHeight - window.innerHeight),
      qr_width: bounds ? Math.round(bounds.width) : 0, qr_height: bounds ? Math.round(bounds.height) : 0,
      chrome_major: Number((/Chrome\/(\d+)/.exec(navigator.userAgent) || [0, 0])[1]),
      css_min: supports("width", "min(1px, 2px)"), css_aspect_ratio: supports("aspect-ratio", "1 / 1"),
      overflow,
    };
  }

  async function heartbeat(view) {
    try {
      const response = await request("POST", "../api/guest/heartbeat", {
        session_id: view.session_id,
        presentation_id: view.presentation_id,
        visible: !document.hidden,
        display: displayMetrics(),
      });
      if (!response.ok) { model.ack = "rejected"; return; }
      const status = await response.json();
      model.ack = status && status.status ? status.status : "unknown";
    } catch (_) {
      model.ack = "unreachable";
    }
  }

  // ---------------------------------------------------------------------------
  // Spotlight: a soft highlight wanders between voice examples so the eye finds them.
  // The highlight element carries a shared view-transition-name, so moving the class
  // morphs the pill from one row to the next.
  // ---------------------------------------------------------------------------
  function moveSpotlight() {
    if (model.transitioning || document.hidden) return;
    const phrases = stage.querySelectorAll(".phrase");
    if (phrases.length < 2) return;
    const next = (model.spot + 1) % phrases.length;
    transition(() => {
      phrases.forEach((element, index) => element.classList.toggle("is-spot", index === next));
      model.spot = next;
    });
  }

  // Burn-in care for a page that may sit on an OLED all week: nudge the whole stage a
  // few millimetres every ten minutes, eased by CSS.
  function drift() {
    const step = () => Math.round((Math.random() - 0.5) * 2 * 100) / 100;
    root.style.setProperty("--drift-x", `calc(var(--u) * ${step() * 0.8})`);
    root.style.setProperty("--drift-y", `calc(var(--u) * ${step() * 0.8})`);
  }

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  applyDaypart(false);
  render(true);
  poll();
  window.setInterval(poll, POLL_MS);
  window.setInterval(() => render(false), 1000);
  window.setInterval(moveSpotlight, SPOTLIGHT_MS);
  window.setInterval(drift, DRIFT_MS);
  if (DAYPART_OVERRIDE === "cycle") {
    window.setInterval(() => {
      if (model.transitioning) return;
      cycleIndex += 1;
      applyDaypart(true);
      tickClock();
    }, DAYPART_CYCLE_MS);
  }
  scheduleClock();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  window.addEventListener("pageshow", (event) => { if (event.persisted) poll(); });
})();
