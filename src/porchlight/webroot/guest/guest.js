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
  };

  // ---------------------------------------------------------------------------
  // Copy and formatting
  // ---------------------------------------------------------------------------
  const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  const longDateFormat = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric" });
  const shortDateFormat = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric" });

  const MODE_LABEL = { off: "Off", heat: "Heat", cool: "Cool", heat_cool: "Auto", auto: "Auto", dry: "Dry", fan_only: "Fan" };
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
  const HINTS = {
    off: "Say <em class=\"wake\">“Alexa, turn on Guest Mode”</em> to show Wi‑Fi and house tips here.",
    unavailable: "Catching up with the house…",
    unlinked: "This screen isn’t linked yet. Open it from Home Assistant’s guest link.",
    boot: "",
  };

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // The palette follows the household's day: dawn-tinted mornings, sunlit afternoons, the
  // lamplit evening, and a dimmer, cooler late night. ?daypart=night forces one for review.
  const DAYPART_OVERRIDE = (/[?&]daypart=(morning|afternoon|evening|night)/.exec(window.location.search) || [])[1] || "";
  function daypart(date) {
    if (DAYPART_OVERRIDE) return DAYPART_OVERRIDE;
    const hour = date.getHours();
    if (hour >= 5 && hour < 11) return "morning";
    if (hour >= 11 && hour < 17) return "afternoon";
    if (hour >= 17 && hour < 22) return "evening";
    return "night";
  }

  function greeting(date) {
    const part = daypart(date);
    if (part === "morning") return "Good morning";
    if (part === "afternoon") return "Good afternoon";
    return "Good evening";
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

  function formatTemp(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    const half = Math.round(value * 2) / 2;
    return Number.isInteger(half) ? String(half) : half.toFixed(1);
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

  // ---------------------------------------------------------------------------
  // Wi-Fi QR, drawn locally from the server's WIFI: payload. The white tile and quiet zone
  // live inside the SVG so the code always stays square and contained in its stage.
  // ---------------------------------------------------------------------------
  function qrSvg(payload) {
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
      return `<svg viewBox="${-quiet} ${-quiet} ${size} ${size}" role="img" aria-label="Wi-Fi join code">`
        + `<rect class="qr-tile" x="${-quiet}" y="${-quiet}" width="${size}" height="${size}" rx="2.4"/>`
        + `<path class="qr-ink" d="${d}"/></svg>`;
    } catch (_) {
      return "";
    }
  }

  // ---------------------------------------------------------------------------
  // Views
  // ---------------------------------------------------------------------------
  function clockHtml(date, variant) {
    const dateText = variant === "neutral" ? longDateFormat.format(date) : shortDateFormat.format(date);
    return `<p class="clock">${esc(timeFormat.format(date))}</p><p class="date">${esc(dateText)}</p>`;
  }

  function statusPill() {
    const now = Date.now();
    const fresh = model.view && now - model.lastGoodAt < STALE_MS;
    if (!model.token) return `<p class="status-pill" data-tone="idle">Not linked</p>`;
    if (!fresh || (model.view && model.view.status === "unavailable")) return `<p class="status-pill" data-tone="stale">Reconnecting\u2026</p>`;
    if (model.view && model.view.enabled) {
      if (model.ack === "active") return `<p class="status-pill" data-tone="live">Live</p>`;
      return `<p class="status-pill" data-tone="sync">Syncing</p>`;
    }
    return `<p class="status-pill" data-tone="idle">Guest mode off</p>`;
  }

  function neutralView(reason) {
    const now = new Date();
    const hint = HINTS[reason] || "";
    return `<section class="neutral" data-view="${esc(reason)}">
      <div class="lamp"><img src="/icon-round.png" alt=""></div>
      <div class="centre">
        <p class="eyebrow greeting">${esc(greeting(now))}</p>
        ${clockHtml(now, "neutral")}
      </div>
      <p class="hint">${hint}</p>
      ${statusPill()}
    </section>`;
  }

  function wifiHtml(view, stale) {
    const wifi = view.wifi;
    if (!wifi) {
      return `<section class="card wifi">
        <div class="card-head"><div><p class="eyebrow">Wi‑Fi</p><h2>Ask us for the Wi‑Fi</h2></div></div>
        <div class="qr-stage"><div class="qr-placeholder">No guest network is set up on this screen yet.</div></div>
      </section>`;
    }
    const open = wifi.security === "nopass";
    const svg = stale ? "" : qrSvg(wifi.qr_payload || "");
    const stageHtml = stale
      ? `<div class="qr-placeholder">Wi‑Fi details will be back in a moment.</div>`
      : (svg || `<div class="qr-placeholder">Join by hand with the details below.</div>`);
    const lead = stale
      ? `<p class="lead">Reconnecting to the house. Nothing to do on your side.</p>`
      : `<p class="lead">Point your phone’s camera at the code and tap <strong>Join</strong>.</p>`;
    const passwordRow = open
      ? `<div><dt>Password</dt><dd class="muted">None needed — just join.</dd></div>`
      : `<div><dt>Password</dt><dd class="password" data-length="${lengthClass(wifi.password, 22, 40)}">${stale ? "••••••••" : esc(wifi.password)}</dd></div>`;
    const note = wifi.hidden
      ? `<p class="note">Hidden network: choose “Other” in your Wi‑Fi settings and type the name exactly.</p>`
      : `<p class="note">Or join by hand from your phone’s Wi‑Fi settings.</p>`;
    return `<section class="card wifi">
      <div class="card-head"><div><p class="eyebrow">Wi‑Fi</p><h2>Get online</h2></div><p class="meta">${open ? "Open network" : "Secure network"}</p></div>
      <div class="qr-stage">${stageHtml}</div>
      ${lead}
      <dl class="creds">
        <div><dt>Network</dt><dd class="ssid" data-length="${lengthClass(wifi.ssid, 18, 99)}">${esc(wifi.ssid)}</dd></div>
        ${passwordRow}
      </dl>
      ${note}
    </section>`;
  }

  function groupHtml(label, icon, phrases) {
    if (!Array.isArray(phrases) || !phrases.length) return "";
    const items = phrases.slice(0, 3).map((phrase) => `<li class="phrase"><span class="spot" aria-hidden="true"></span><span class="text">“${phraseHtml(phrase)}”</span></li>`).join("");
    return `<div class="group"><h3>${icon}${esc(label)}</h3><ul class="phrases">${items}</ul></div>`;
  }

  function voiceHtml(view) {
    const alexa = view.alexa || {};
    const groups = groupHtml("Lights", ICONS.bulb, alexa.lights) + groupHtml("Music", ICONS.note, alexa.music) + groupHtml("Blinds", ICONS.blind, alexa.blinds);
    if (!groups) return "";
    const count = ["lights", "music", "blinds"].reduce((total, key) => total + Math.min(3, (alexa[key] || []).length), 0);
    return `<section class="card voice" data-phrases="${count}">
      <div class="card-head"><div><p class="eyebrow">Voice</p><h2>Just ask Alexa</h2></div><p class="meta">Speak naturally</p></div>
      <div class="groups">${groups}</div>
    </section>`;
  }

  function zoneHtml(zone, index, stale) {
    const available = !stale && zone.available;
    const unit = zone.unit === "°C" ? "C" : "F";
    const current = available ? formatTemp(zone.current_temperature) : null;
    const low = available ? formatTemp(zone.target_temperature_low) : null;
    const high = available ? formatTemp(zone.target_temperature_high) : null;
    const target = available ? formatTemp(zone.target_temperature) : null;
    let detail = "";
    if (low && high) detail = `<span class="target">Keeping ${esc(low)}–${esc(high)}°</span>`;
    else if (target) detail = `<span class="target">Set to ${esc(target)}°</span>`;
    let chip = "";
    if (available && (zone.mode || zone.action)) {
      const parts = [MODE_LABEL[zone.mode], ACTION_LABEL[zone.action]].filter(Boolean);
      chip = `<span class="chip" data-action="${esc(zone.action || "")}">${esc(parts.join(" · "))}</span>`;
    }
    if (!available) detail = `<span>${stale ? "Catching up…" : "Not reporting right now"}</span>`;
    const temp = current == null
      ? `<p class="zone-temp is-blank" data-zone="${index}">—</p>`
      : `<p class="zone-temp" data-zone="${index}">${esc(current)}°<sup>${unit}</sup></p>`;
    return `<article class="zone">${temp}<p class="zone-label">${esc(zone.label || "Climate")}</p><p class="zone-detail">${detail}${chip}</p></article>`;
  }

  function comfortHtml(view, stale) {
    const zones = Array.isArray(view.hvac) ? view.hvac.slice(0, 8) : [];
    if (!zones.length) return "";
    return `<section class="card comfort" data-zones="${zones.length}">
      <div class="card-head"><div><p class="eyebrow">Comfort</p><h2>${zones.length === 1 ? "Climate" : "Climate by room"}</h2></div><p class="meta">Read-only</p></div>
      <div class="zones">${zones.map((zone, index) => zoneHtml(zone, index, stale)).join("")}</div>
    </section>`;
  }

  function guestView(view, stale) {
    const now = new Date();
    return `<section class="guest" data-view="${stale ? "stale" : "active"}">
      ${wifiHtml(view, stale)}
      <div class="main">
        <header class="welcome">
          <p class="eyebrow greeting">${esc(greeting(now))}</p>
          <h1 class="headline">${esc(view.welcome || "Welcome")}</h1>
          <p class="subtitle">${esc(view.title || "")}</p>
        </header>
        ${voiceHtml(view) || `<section class="card voice"><div class="card-head"><div><p class="eyebrow">Voice</p><h2>Just ask Alexa</h2></div></div><p class="lead">Ask Alexa for lights and music the way you would at home.</p></section>`}
        ${comfortHtml(view, stale) || `<section class="card comfort" data-zones="0"><div class="card-head"><div><p class="eyebrow">Comfort</p><h2>Climate</h2></div></div><p class="empty">Make yourself comfortable — let us know if a room needs adjusting.</p></section>`}
      </div>
      <footer class="foot">
        <div class="brand"><div class="lamp"><img src="/icon-round.png" alt=""></div><p class="wordmark">Porchlight</p></div>
        ${statusPill()}
        <p class="exit-hint">Hosts: <em class="wake">“Alexa, turn off Guest Mode”</em> clears this screen.</p>
        <div class="time">${clockHtml(now, "guest")}</div>
      </footer>
    </section>`;
  }

  // ---------------------------------------------------------------------------
  // State derivation. The browser enforces freshness on its own clock as well: if the
  // view has not been refreshed within STALE_MS the credentials leave the screen.
  // ---------------------------------------------------------------------------
  function derive() {
    const now = Date.now();
    if (!model.token) return { screen: "neutral", reason: "unlinked" };
    const view = model.view;
    const fresh = !!view && now - model.lastGoodAt < STALE_MS;
    if (!view) return { screen: "neutral", reason: model.error ? "unavailable" : "boot" };
    if (!view.enabled) return { screen: "neutral", reason: fresh && view.status === "off" ? "off" : "unavailable" };
    return { screen: "guest", stale: !fresh };
  }

  function renderKey(state) {
    const view = model.view || {};
    const significant = state.screen === "guest"
      ? [view.session_id, view.presentation_id, view.welcome, view.title, view.wifi, view.alexa,
         (view.hvac || []).map((zone) => [zone.id, zone.label, zone.available, zone.unit, zone.mode, zone.action,
           formatTemp(zone.current_temperature), formatTemp(zone.target_temperature),
           formatTemp(zone.target_temperature_low), formatTemp(zone.target_temperature_high)])]
      : [];
    return JSON.stringify([state.screen, state.reason || "", !!state.stale, model.ack, !model.token, significant]);
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
    const key = renderKey(state);
    if (!force && key === model.key) {
      tickClock();
      return;
    }
    model.key = key;
    const html = state.screen === "guest" ? guestView(model.view, state.stale) : neutralView(state.reason);
    transition(() => {
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
    const greet = stage.querySelector(".greeting");
    if (clock) clock.textContent = timeFormat.format(now);
    if (date) date.textContent = (stage.querySelector(".neutral") ? longDateFormat : shortDateFormat).format(now);
    if (greet) greet.textContent = greeting(now);
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
  async function poll() {
    if (polling || !model.token) return;
    polling = true;
    try {
      const response = await request("GET", "/api/guest");
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
      if (view.enabled && view.session_id && view.presentation_id) {
        await heartbeat(view);
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

  async function heartbeat(view) {
    try {
      const response = await request("POST", "/api/guest/heartbeat", {
        session_id: view.session_id,
        presentation_id: view.presentation_id,
        visible: !document.hidden,
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
  scheduleClock();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  window.addEventListener("pageshow", (event) => { if (event.persisted) poll(); });
})();
