const state = {
  status: {},
  hosts: [],
  services: [],
  changes: { recent_runs: [] },
  analysis: { status: "missing" },
  snapshot: {},
  query: "",
  statusFilter: "all",
  groupBy: "subnet",
  currentRoute: null,
  suppressHashRender: false,
  setupStatus: { setup: {}, mqtt: {}, openai: {}, wifi: {} },
};

const themeModes = ["light", "system", "dark"];
const themeLabels = { light: "Light", system: "System", dark: "Dark" };

function preferredThemeMode() {
  const saved = window.localStorage.getItem("porchlight-theme");
  return themeModes.includes(saved) ? saved : "system";
}

function resolvedTheme(mode) {
  if (mode === "dark" || mode === "light") return mode;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(mode) {
  const selected = themeModes.includes(mode) ? mode : "system";
  document.documentElement.dataset.themeMode = selected;
  document.documentElement.dataset.theme = resolvedTheme(selected);
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    const active = button.dataset.themeChoice === selected;
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", active ? "true" : "false");
    button.setAttribute("aria-label", themeLabels[button.dataset.themeChoice] || "Theme");
    button.setAttribute("title", themeLabels[button.dataset.themeChoice] || "Theme");
  });
}

function compactThemeToggle() {
  return window.matchMedia && window.matchMedia("(max-width: 820px)").matches;
}

function nextThemeMode(mode) {
  const index = themeModes.indexOf(mode);
  return themeModes[(index + 1) % themeModes.length] || "system";
}

function bindThemeToggle() {
  applyTheme(preferredThemeMode());
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.addEventListener("click", () => {
      const current = preferredThemeMode();
      const choice = compactThemeToggle() && button.dataset.themeChoice === current
        ? nextThemeMode(current)
        : button.dataset.themeChoice || "system";
      window.localStorage.setItem("porchlight-theme", choice);
      applyTheme(choice);
    });
  });
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (document.documentElement.dataset.themeMode === "system") applyTheme("system");
    });
  }
}

bindThemeToggle();

const protocolColor = {
  ssh: "var(--porch-amber)",
  http: "var(--porch-leaf)",
  https: "var(--porch-leaf)",
  mqtt: "var(--porch-sky)",
  rtsp: "var(--porch-clay)",
  "rtsp-alt": "var(--porch-clay)",
  domain: "var(--porch-sky)",
  "microsoft-ds": "var(--porch-clay)",
  "netbios-ssn": "var(--porch-clay)",
  "ms-wbt-server": "var(--porch-clay)",
  vnc: "var(--porch-clay)",
  "http-proxy": "var(--porch-leaf)",
  upnp: "var(--porch-sky)",
  wsdapi: "var(--porch-sky)",
  polipo: "var(--porch-leaf)",
  "https-alt": "var(--porch-leaf)",
  ppp: "var(--porch-sky)",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function href(route) {
  return `#${route}`;
}

function route() {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  return raw.startsWith("/") ? raw : `/${raw}`;
}

function activeNav() {
  const current = route();
  document.querySelectorAll(".nav a, .drawer-nav a").forEach((link) => {
    const target = link.getAttribute("data-route");
    link.classList.toggle("active", target === "/" ? current === "/" : current.startsWith(target));
  });
}

function closeDrawer() {
  document.body.classList.remove("drawer-open");
  const drawer = document.querySelector(".mobile-drawer");
  const backdrop = document.querySelector(".drawer-backdrop");
  const button = document.querySelector(".menu-toggle");
  if (drawer) drawer.setAttribute("aria-hidden", "true");
  if (button) button.setAttribute("aria-expanded", "false");
  if (backdrop) backdrop.hidden = true;
}

function openDrawer() {
  const drawer = document.querySelector(".mobile-drawer");
  const backdrop = document.querySelector(".drawer-backdrop");
  const button = document.querySelector(".menu-toggle");
  if (backdrop) backdrop.hidden = false;
  requestAnimationFrame(() => document.body.classList.add("drawer-open"));
  if (drawer) drawer.setAttribute("aria-hidden", "false");
  if (button) button.setAttribute("aria-expanded", "true");
}

function bindChrome() {
  const header = document.querySelector(".site-header");
  const updateScrolled = () => header?.setAttribute("data-scrolled", window.scrollY > 8 ? "true" : "false");
  updateScrolled();
  window.addEventListener("scroll", updateScrolled, { passive: true });
  document.querySelector(".menu-toggle")?.addEventListener("click", () => {
    document.body.classList.contains("drawer-open") ? closeDrawer() : openDrawer();
  });
  document.querySelector(".drawer-backdrop")?.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawer();
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href^='#/']");
    if (!link) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigateTo(link.getAttribute("href").slice(1));
  });
}

async function json(path, fallback) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) return fallback;
  return response.json();
}

async function load() {
  const [status, hosts, services, changes, analysis, snapshot, setupStatus] = await Promise.all([
    json("/status.json", {}),
    json("/hosts.json", { hosts: [] }),
    json("/services.json", { services: [] }),
    json("/changes.json", { recent_runs: [] }),
    json("/analysis.json", { status: "missing" }),
    json("/snapshot.json", {}),
    json("/api/setup/status", { setup: {}, mqtt: {}, openai: {}, wifi: {} }),
  ]);
  state.status = status || {};
  state.hosts = Array.isArray(hosts.hosts) ? hosts.hosts : [];
  state.services = Array.isArray(services.services) ? services.services : [];
  state.changes = changes || { recent_runs: [] };
  state.analysis = analysis || { status: "missing" };
  state.snapshot = snapshot || {};
  state.setupStatus = setupStatus || { setup: {}, mqtt: {}, openai: {}, wifi: {} };
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) throw new Error(data.error || `Request failed with ${response.status}`);
  return data;
}

function number(value) {
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function displayName(host) {
  return host.display_name || host.hostname || host.ip || "unknown";
}

function serviceName(service) {
  return service.service_name || service.category || "unknown";
}

function category(service) {
  return service.category || "internal";
}

function hostByIp(ip) {
  return state.hosts.find((host) => host.ip === ip);
}

function servicesForHost(ip) {
  return state.services.filter((service) => service.ip === ip);
}

function derivedServiceCounts() {
  if (!state.services.length) {
    return {
      open_ports: number(state.status.open_ports),
      http_services: number(state.status.http_services),
      rtsp_services: number(state.status.rtsp_services),
      mqtt_services: number(state.status.mqtt_services),
      internal_services: number(state.status.internal_services),
    };
  }
  const counts = {
    open_ports: state.services.length,
    http_services: 0,
    rtsp_services: 0,
    mqtt_services: 0,
    internal_services: 0,
  };
  state.services.forEach((service) => {
    const serviceCategory = category(service);
    if (serviceCategory === "http") counts.http_services += 1;
    else if (serviceCategory === "rtsp") counts.rtsp_services += 1;
    else if (serviceCategory === "mqtt") counts.mqtt_services += 1;
    else if (serviceCategory === "internal") counts.internal_services += 1;
  });
  return counts;
}

function hostsForService(name) {
  const ips = new Set(state.services.filter((service) => serviceName(service) === name).map((service) => service.ip));
  return state.hosts.filter((host) => ips.has(host.ip));
}

function ipNum(ip) {
  return String(ip || "")
    .split(".")
    .reduce((sum, part, index) => sum + (Number.parseInt(part, 10) || 0) * Math.pow(256, 3 - index), 0);
}

function subnetOf(ip) {
  const parts = String(ip || "").split(".");
  return parts.length === 4 ? `${parts[0]}.${parts[1]}.${parts[2]}.0/24` : "other";
}

function groupBySubnet(hosts = state.hosts) {
  const groups = new Map();
  hosts.forEach((host) => {
    const key = subnetOf(host.ip);
    groups.set(key, [...(groups.get(key) || []), host]);
  });
  return Array.from(groups, ([subnet, list]) => ({
    subnet,
    hosts: list.sort((a, b) => ipNum(a.ip) - ipNum(b.ip)),
  })).sort((a, b) => a.subnet.localeCompare(b.subnet));
}

function uniqueProtocols() {
  const groups = new Map();
  state.services.forEach((service) => {
    const name = serviceName(service);
    const existing = groups.get(name) || { count: 0, ips: new Set() };
    existing.count += 1;
    existing.ips.add(service.ip);
    groups.set(name, existing);
  });
  return Array.from(groups, ([name, item]) => ({ name, count: item.count, hosts: item.ips.size }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

function uniqueCategories() {
  const groups = new Map();
  state.services.forEach((service) => {
    const name = category(service);
    const existing = groups.get(name) || { count: 0, ips: new Set() };
    existing.count += 1;
    existing.ips.add(service.ip);
    groups.set(name, existing);
  });
  return Array.from(groups, ([name, item]) => ({ name, count: item.count, hosts: item.ips.size }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

function relativeTime(iso) {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return iso;
  const diff = Math.max(0, Date.now() - then);
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function gradeColor(grade) {
  return {
    A: "var(--porch-leaf)",
    B: "var(--porch-amber)",
    C: "#c99634",
    D: "var(--porch-clay)",
    F: "#b12f2d",
  }[grade] || "var(--porch-amber)";
}

function protocolTone(name) {
  if (["http", "https", "http-proxy", "https-alt", "polipo"].includes(name)) return "leaf";
  if (name === "ssh") return "amber";
  if (["mqtt", "domain", "wsdapi", "upnp", "ppp"].includes(name)) return "sky";
  return "clay";
}

function chip(name, count) {
  return `<span class="chip mono" data-tone="${protocolTone(name)}"><span style="width:.42rem;height:.42rem;border-radius:50%;background:${protocolColor[name] || "var(--porch-ink-soft)"}"></span>${escapeHtml(name)}${count == null ? "" : `<span class="muted">- ${escapeHtml(count)}</span>`}</span>`;
}

function statusDot(status) {
  return `<span class="dot ${status === "inactive" ? "inactive" : ""}" aria-label="${escapeHtml(status || "active")}"></span>`;
}

function stat(label, value, hint, tone) {
  return `<article class="card stat" style="--tone:${tone || "var(--porch-amber)"}">
    <div class="stat-label">${escapeHtml(label)}</div>
    <div class="stat-value">${escapeHtml(value)}</div>
    <div class="stat-hint">${escapeHtml(hint || "")}</div>
  </article>`;
}

function sectionHead(eyebrow, title, aside = "") {
  return `<div class="section-head">
    <div>
      ${eyebrow ? `<p class="eyebrow">${escapeHtml(eyebrow)}</p>` : ""}
      <h2>${escapeHtml(title)}</h2>
    </div>
    ${aside ? `<div class="small">${aside}</div>` : ""}
  </div>`;
}

function aiAnalysisReady() {
  const openai = state.setupStatus.openai || {};
  return Boolean(
    openai.analysis_enabled
      && state.analysis
      && state.analysis.environment
      && (state.analysis.status === "ok" || state.analysis.analysis_stale)
  );
}

function generatedEnvironmentAnalysis() {
  if (!aiAnalysisReady() || !state.analysis.environment) return null;
  return {
    ...state.analysis.environment,
    scope: "AI - environment",
  };
}

function generatedProtocolAnalysis(name) {
  if (!aiAnalysisReady() || !Array.isArray(state.analysis.protocols)) return null;
  const item = state.analysis.protocols.find((analysis) => analysis.name === name);
  return item ? { ...item, scope: `AI - protocol - ${name}` } : null;
}

function generatedHostAnalysis(ip) {
  if (!aiAnalysisReady() || !Array.isArray(state.analysis.hosts)) return null;
  const item = state.analysis.hosts.find((analysis) => analysis.ip === ip);
  return item ? { ...item, scope: `AI - host - ${ip}`, concerns: item.notes || [] } : null;
}

function analysisStatusText(openai) {
  const status = openai.analysis_status || state.analysis || {};
  const parts = [`Last analysis: ${analysisStatusLabel(status.status)}`];
  if (status.generated_at) parts.push(status.generated_at);
  if (status.model) parts.push(status.model);
  if (status.service_tier) parts.push(status.service_tier);
  if (status.retry_after) parts.push(`retry after ${status.retry_after}`);
  if (status.last_success_at) parts.push(`last successful ${status.last_success_at}`);
  if (status.error) parts.push(status.error);
  return parts.join(" - ");
}

function analysisStatusLabel(status) {
  return {
    missing_key: "missing key",
    missing_snapshot: "missing snapshot",
    rate_limited: "rate limited",
    upstream_error: "upstream error",
    invalid_response: "invalid response",
    request_failed: "request failed",
  }[status] || status || "missing";
}

function analysisForEnvironment() {
  const generated = generatedEnvironmentAnalysis();
  if (generated) return generated;
  const status = state.status;
  const serviceCounts = derivedServiceCounts();
  const hostCount = number(status.hosts_seen);
  const active = number(status.active_hosts);
  const openPorts = serviceCounts.open_ports;
  const changed = number(status.changed_services);
  const health = status.health || "unknown";
  const grade = health === "healthy" ? (changed ? "B" : "A") : "C";
  return {
    grade,
    scope: "environment",
    headline: health === "healthy" ? "Network view is current." : "Network view needs attention.",
    summary: `${active} of ${hostCount} hosts answered the latest scan, with ${openPorts} open ports indexed. The scanner reports ${health}.`,
    highlights: [
      `${serviceCounts.http_services} HTTP, ${serviceCounts.rtsp_services} RTSP, and ${serviceCounts.mqtt_services} MQTT services are visible.`,
      `The appliance rendered this snapshot ${relativeTime(status.last_scan)}.`,
    ],
    concerns: status.scan_blocked ? [status.scan_blocked] : changed ? [`${changed} services changed since the previous scan.`] : [],
    suggestions: [
      "Review the exposure lenses first, then drill into individual hosts.",
      "Keep active scan scope bounded by private CIDR and interface policy.",
    ],
  };
}

function analysisForProtocol(name) {
  const generated = generatedProtocolAnalysis(name);
  if (generated) return generated;
  const matching = state.services.filter((service) => serviceName(service) === name);
  const hostCount = new Set(matching.map((service) => service.ip)).size;
  const hostVerb = hostCount === 1 ? "speaks" : "speak";
  const serviceVerb = matching.length === 1 ? "is" : "are";
  const grade = ["ms-wbt-server", "rtsp", "netbios-ssn"].includes(name) ? "C" : name === "mqtt" ? "A" : "B";
  return {
    grade,
    scope: `protocol - ${name}`,
    headline: `${hostCount} host${hostCount === 1 ? "" : "s"} ${hostVerb} ${name}.`,
    summary: `${matching.length} ${name} service${matching.length === 1 ? "" : "s"} ${serviceVerb} reachable from the scanner.`,
    highlights: matching.slice(0, 3).map((service) => `${service.ip} answers on ${service.proto}/${service.port}.`),
    concerns: ["rtsp", "ms-wbt-server", "netbios-ssn", "vnc"].includes(name)
      ? ["Confirm this surface is expected on every listed host."]
      : [],
    suggestions: [],
  };
}

function analysisForHost(host) {
  const generated = generatedHostAnalysis(host.ip);
  if (generated) return generated;
  const services = servicesForHost(host.ip);
  const risky = services.filter((service) => ["rtsp", "ms-wbt-server", "netbios-ssn", "vnc"].includes(serviceName(service)));
  return {
    grade: risky.length ? "C" : services.length > 5 ? "B" : "A",
    scope: `host - ${displayName(host)}`,
    headline: risky.length ? "This host has surfaces worth checking." : "This host looks ordinary from the scanner.",
    summary: `${displayName(host)} exposes ${services.length} service${services.length === 1 ? "" : "s"} and was last seen ${relativeTime(host.last_seen_at)}.`,
    highlights: services.slice(0, 4).map((service) => `${service.proto}/${service.port} ${serviceName(service)}`),
    concerns: risky.map((service) => `${serviceName(service)} on ${service.proto}/${service.port}`),
    suggestions: [],
  };
}

function analysisCard(analysis) {
  return `<article class="card analysis">
    <div class="analysis-top">
      <span class="grade" style="--grade-color:${gradeColor(analysis.grade)}">${escapeHtml(analysis.grade)}</span>
      <div>
        <p class="eyebrow">${escapeHtml(analysis.scope)}</p>
        <h3>${escapeHtml(analysis.headline)}</h3>
        <p style="margin-top:.45rem">${escapeHtml(analysis.summary)}</p>
      </div>
    </div>
    ${listBlock("Highlights", analysis.highlights)}
    ${listBlock("Concerns", analysis.concerns)}
    ${listBlock("Suggestions", analysis.suggestions)}
  </article>`;
}

function listBlock(title, items = []) {
  const filtered = items.filter(Boolean);
  if (!filtered.length) return "";
  return `<div>
    <p class="eyebrow">${escapeHtml(title)}</p>
    <ul class="note-list">${filtered.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
  </div>`;
}

function recentIrregularities(limit = 8) {
  const items = Array.isArray(state.changes.irregularities) ? state.changes.irregularities : [];
  return items.slice(0, limit);
}

function renderIrregularitiesSection(limit = 8) {
  const items = recentIrregularities(limit);
  return `<section class="section">
    ${sectionHead("Scan changes", "Irregularities since comparable scans", `${items.length} shown`)}
    <div class="grid two">${items.map(irregularityCard).join("") || empty("No scan-to-scan irregularities in the latest comparable scans.")}</div>
  </section>`;
}

function irregularityCard(item) {
  const severity = item.severity || "notice";
  const observed = item.observed_at ? ` - ${relativeTime(item.observed_at)}` : "";
  return `<article class="link-card irregularity" data-severity="${escapeHtml(severity)}">
    <p class="eyebrow">${escapeHtml(item.kind || "irregularity")}${escapeHtml(observed)}</p>
    <h3>${escapeHtml(item.title || "Scan irregularity")}</h3>
    <p class="small">${escapeHtml(item.summary || "")}</p>
  </article>`;
}

function hostRow(host) {
  const services = servicesForHost(host.ip);
  const serviceChips = services.length
    ? services.slice(0, 6).map((service) => chip(serviceName(service), service.port)).join("")
    : `<span class="small">no open ports</span>`;
  return `<a class="host-row" href="${href(`/hosts/${encodeURIComponent(host.ip)}`)}">
    ${statusDot(host.status)}
    <span class="host-title">
      <strong>${escapeHtml(displayName(host))}</strong>
      <span class="small mono">${escapeHtml(host.ip)}${host.mac ? ` - ${escapeHtml(host.mac)}` : ""}</span>
    </span>
    <span class="chips">${serviceChips}${services.length > 6 ? `<span class="small">+${services.length - 6}</span>` : ""}</span>
  </a>`;
}

function renderOverview() {
  const status = state.status;
  const protocols = uniqueProtocols();
  const categories = uniqueCategories();
  const serviceCounts = derivedServiceCounts();
  const featured = state.hosts
    .filter((host) => host.status === "active")
    .sort((a, b) => servicesForHost(b.ip).length - servicesForHost(a.ip).length)
    .slice(0, 5);
  const sshHosts = new Set(state.services.filter((service) => serviceName(service) === "ssh").map((service) => service.ip)).size;
  const rtspHosts = new Set(state.services.filter((service) => category(service) === "rtsp").map((service) => service.ip)).size;
  const httpServices = state.services.filter((service) => category(service) === "http").length;
  return `<div class="stack">
    <section class="hero">
      <div class="hero-row">
        <div>
          <p class="eyebrow">${escapeHtml(status.network_cidr || "network unknown")} - gateway ${escapeHtml(status.gateway || "unknown")}</p>
          <h1>${escapeHtml(status.health === "healthy" ? "Network view is current." : "Network view needs attention.")}</h1>
        </div>
        <span class="scan-pill">${statusDot(status.scanner_online === false ? "inactive" : "active")} scan ${escapeHtml(status.scan_state || "unknown")}</span>
      </div>
      <p>${number(status.active_hosts)} of ${number(status.hosts_seen)} hosts answered the latest scan. Last sweep ${relativeTime(status.last_scan)}. Scanner health is ${escapeHtml(status.health || "unknown")}.</p>
      <div class="stats">
        ${stat("Active hosts", number(status.active_hosts), `${Math.max(0, number(status.hosts_seen) - number(status.active_hosts))} dormant`, "var(--porch-leaf)")}
        ${stat("Open ports", serviceCounts.open_ports, `${number(status.changed_services)} changed`, "var(--porch-amber)")}
        ${stat("HTTP services", serviceCounts.http_services, `${serviceCounts.internal_services} internal`, "var(--porch-sky)")}
        ${stat("MQTT · RTSP", `${serviceCounts.mqtt_services} · ${serviceCounts.rtsp_services}`, `${number(status.new_hosts)} new hosts`, "var(--porch-clay)")}
      </div>
    </section>
    <section class="section">
      ${sectionHead("Daily analysis", "Today, at an environment level", `<a href="${href("/analysis")}">See all analyses</a>`)}
      ${analysisCard(analysisForEnvironment())}
    </section>
    ${renderIrregularitiesSection(4)}
    <section class="section">
      ${sectionHead("Worth a glance", "Surfaces that show up the most")}
      <div class="grid three">
        ${exposureCard("ssh", "SSH endpoints", sshHosts, "open to anything on the LAN")}
        ${exposureCard("rtsp", "RTSP cameras", rtspHosts, "streaming endpoints")}
        ${exposureCard("http", "HTTP admin pages", httpServices, "plain or local web surfaces")}
      </div>
    </section>
    <section class="section">
      ${sectionHead("Group by", "Protocols on the network", `<a href="${href("/protocols")}">All protocols</a>`)}
      <div class="grid four">${protocols.map(protocolCard).join("")}</div>
      <div class="chips"><span class="small">By category</span>${categories.map((item) => chip(item.name, item.count)).join("")}</div>
    </section>
    <section class="section">
      ${sectionHead("Group by", "Featured hosts", `<a href="${href("/hosts")}">All ${state.hosts.length} hosts</a>`)}
      <div class="grid">${featured.map(hostRow).join("") || empty("No hosts found.")}</div>
    </section>
  </div>`;
}

function exposureCard(name, label, count, blurb) {
  return `<a class="link-card exposure-card" href="${href(name === "ssh" ? "/protocols/ssh" : "/exposures")}">
    <p class="eyebrow">${escapeHtml(label)}</p>
    <div class="stat-value">${escapeHtml(count)}</div>
    <p class="small">${escapeHtml(blurb)}</p>
  </a>`;
}

function protocolCard(item) {
  const analysis = analysisForProtocol(item.name);
  return `<a class="link-card protocol-card" href="${href(`/protocols/${encodeURIComponent(item.name)}`)}">
    <div class="chips" style="justify-content:space-between">
      ${chip(item.name)}
      <span class="grade" style="width:2rem;height:2rem;font-size:1rem;--grade-color:${gradeColor(analysis.grade)}">${analysis.grade}</span>
    </div>
    <p class="small" style="margin-top:.8rem">${item.count} service${item.count === 1 ? "" : "s"} - ${item.hosts} host${item.hosts === 1 ? "" : "s"}</p>
  </a>`;
}

function renderHosts() {
  const term = state.query.trim().toLowerCase();
  const filtered = state.hosts
    .filter((host) => state.statusFilter === "all" || host.status === state.statusFilter)
    .filter((host) => {
      if (!term) return true;
      return [displayName(host), host.ip, host.mac, host.names, host.interface].some((value) => String(value || "").toLowerCase().includes(term));
    })
    .sort((a, b) => ipNum(a.ip) - ipNum(b.ip));
  return `<div class="stack">
    <section class="section">
      ${sectionHead("Directory", "Every known host", `${filtered.length} of ${state.hosts.length} hosts - ${state.services.length} services indexed`)}
      <div class="toolbar">
        <input class="search" id="host-search" value="${escapeHtml(state.query)}" placeholder="Search by name, IP, MAC">
        <span class="segmented" data-control="status">${button("all", "All", state.statusFilter)}${button("active", "Active", state.statusFilter)}${button("inactive", "Dormant", state.statusFilter)}</span>
        <span class="segmented" data-control="group">${button("flat", "Flat", state.groupBy)}${button("subnet", "Subnet", state.groupBy)}${button("status", "Status", state.groupBy)}${button("protocol", "Protocol", state.groupBy)}</span>
      </div>
    </section>
    <section class="section">${renderHostGroups(filtered)}</section>
  </div>`;
}

function button(value, label, current) {
  return `<button data-value="${value}" class="${value === current ? "active" : ""}">${label}</button>`;
}

function renderHostGroups(hosts) {
  let groups;
  if (state.groupBy === "flat") {
    groups = [{ label: `${hosts.length} hosts`, hosts }];
  } else if (state.groupBy === "status") {
    groups = ["active", "inactive"].map((status) => ({ label: status, hosts: hosts.filter((host) => host.status === status) })).filter((group) => group.hosts.length);
  } else if (state.groupBy === "protocol") {
    const map = new Map();
    hosts.forEach((host) => {
      const services = servicesForHost(host.ip);
      const names = services.length ? Array.from(new Set(services.map(serviceName))) : ["(no open ports)"];
      names.forEach((name) => map.set(name, [...(map.get(name) || []), host]));
    });
    groups = Array.from(map, ([label, list]) => ({ label, hosts: list })).sort((a, b) => b.hosts.length - a.hosts.length);
  } else {
    groups = groupBySubnet(hosts).map((group) => ({ label: group.subnet, hosts: group.hosts }));
  }
  if (!groups.length) return empty("No hosts match the current filter.");
  return groups.map((group) => `<div class="section">
    <div class="section-head">
      <h3 class="mono">${escapeHtml(group.label)}</h3>
      <span class="small">${group.hosts.length} host${group.hosts.length === 1 ? "" : "s"}</span>
    </div>
    <div class="grid">${group.hosts.map(hostRow).join("")}</div>
  </div>`).join("");
}

function renderHostDetail(ip) {
  const host = hostByIp(ip);
  if (!host) return notFound("Host not found.");
  const services = servicesForHost(host.ip);
  const neighbors = state.hosts.filter((item) => subnetOf(item.ip) === subnetOf(host.ip) && item.ip !== host.ip).slice(0, 12);
  return `<div class="stack">
    <a class="small" href="${href("/hosts")}">Back to hosts</a>
    <section class="hero">
      <p class="eyebrow">${escapeHtml(host.status || "unknown")} - ${escapeHtml(subnetOf(host.ip))}</p>
      <h1>${escapeHtml(displayName(host))}</h1>
      <p class="mono">${escapeHtml(host.ip)}${host.mac ? ` - ${escapeHtml(host.mac)}` : ""}${host.interface ? ` - via ${escapeHtml(host.interface)}` : ""}</p>
    </section>
    ${analysisCard(analysisForHost(host))}
    <section class="section">
      ${sectionHead("Open ports", `${services.length} service${services.length === 1 ? "" : "s"} answering`)}
      ${serviceTable(services)}
    </section>
    <section class="section">
      ${sectionHead("Same subnet", "Neighbors on this segment", escapeHtml(subnetOf(host.ip)))}
      <div class="chips">${neighbors.map((item) => `<a class="chip" href="${href(`/hosts/${encodeURIComponent(item.ip)}`)}">${statusDot(item.status)}${escapeHtml(displayName(item))}<span class="muted mono">${escapeHtml(item.ip)}</span></a>`).join("") || `<span class="small">No neighbors indexed.</span>`}</div>
    </section>
  </div>`;
}

function serviceTable(services) {
  if (!services.length) return `<p class="muted">No open ports on this host. It answered host evidence but did not respond to port probes.</p>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Port</th><th>Service</th><th>Category</th><th>Product</th><th>Link</th></tr></thead>
    <tbody>${services.map((service) => `<tr>
      <td class="mono">${escapeHtml(service.proto)}/${escapeHtml(service.port)}</td>
      <td>${chip(serviceName(service))}</td>
      <td>${escapeHtml(category(service))}</td>
      <td>${escapeHtml(service.product || service.version || "")}</td>
      <td>${service.url ? `<a href="${escapeHtml(service.url)}" target="_blank" rel="noreferrer noopener">open</a>` : `<span class="muted">none</span>`}</td>
    </tr>`).join("")}</tbody>
  </table></div>`;
}

function renderProtocols() {
  const protocols = uniqueProtocols();
  const categories = uniqueCategories();
  return `<div class="stack">
    <section class="section">
      ${sectionHead("Group by", "Protocols on the network", `${state.services.length} services across ${protocols.length} protocols`)}
      <div class="grid three">${protocols.map(protocolCard).join("") || empty("No services indexed yet.")}</div>
    </section>
    <section class="section">
      ${sectionHead("By category", "Higher-level lenses")}
      <div class="chips">${categories.map((item) => chip(item.name, item.count)).join("")}</div>
    </section>
  </div>`;
}

function renderProtocolDetail(name) {
  const matching = state.services.filter((service) => serviceName(service) === name);
  if (!matching.length) return notFound("Protocol not found.");
  const hosts = hostsForService(name);
  const ports = Array.from(new Set(matching.map((service) => `${service.proto}/${service.port}`))).sort();
  const adjacent = Array.from(new Set(hosts.flatMap((host) => servicesForHost(host.ip).map(serviceName)).filter((item) => item !== name))).sort();
  return `<div class="stack">
    <a class="small" href="${href("/protocols")}">Back to protocols</a>
    <section class="hero">
      <p class="eyebrow">protocol</p>
      <h1 class="mono">${escapeHtml(name)}</h1>
      <p>${matching.length} services on ${hosts.length} hosts. Ports: ${escapeHtml(ports.join(", "))}.</p>
    </section>
    ${analysisCard(analysisForProtocol(name))}
    <section class="section">
      ${sectionHead("See all", `Hosts speaking ${name}`, `${hosts.length} of ${state.hosts.length} hosts`)}
      <div class="grid">${hosts.map(hostRow).join("")}</div>
    </section>
    <section class="section">
      ${sectionHead("Adjacent", "Other protocols on these hosts")}
      <div class="chips">${adjacent.map((item) => `<a href="${href(`/protocols/${encodeURIComponent(item)}`)}">${chip(item)}</a>`).join("") || `<span class="small">No adjacent protocols.</span>`}</div>
    </section>
  </div>`;
}

function renderExposures() {
  const buckets = [
    {
      id: "ssh",
      title: "Exposed SSH",
      blurb: "Every host that answered on tcp/22.",
      match: (service) => serviceName(service) === "ssh",
    },
    {
      id: "rtsp",
      title: "RTSP cameras",
      blurb: "Streaming endpoints visible to the scanner.",
      match: (service) => category(service) === "rtsp",
    },
    {
      id: "plain-http",
      title: "Plain :80 with no TLS twin",
      blurb: "HTTP on :80 where this snapshot did not see :443 on the same host.",
      match: (service) => category(service) === "http" && number(service.port) === 80 && !state.services.some((other) => other.ip === service.ip && number(other.port) === 443),
    },
    {
      id: "windows",
      title: "Windows surfaces",
      blurb: "SMB, RDP, and NetBIOS surfaces.",
      match: (service) => ["microsoft-ds", "ms-wbt-server", "netbios-ssn"].includes(serviceName(service)),
    },
  ];
  return `<div class="stack">
    <section class="hero">
      <p class="eyebrow">Posture lens</p>
      <h1>Surfaces visible from the LAN.</h1>
      <p>Porchlight keeps scanning bounded to hosts already seen through local evidence. These lenses show the surfaces to check first.</p>
    </section>
    ${buckets.map((bucket) => {
      const matches = state.services.filter(bucket.match);
      const ips = Array.from(new Set(matches.map((service) => service.ip)));
      return `<section class="section">
        ${sectionHead("Lens", bucket.title, `${matches.length} services on ${ips.length} hosts`)}
        <p class="muted">${escapeHtml(bucket.blurb)}</p>
        <div class="grid two">${ips.map((ip) => exposureHost(ip, matches.filter((service) => service.ip === ip))).join("") || empty("No matches in this snapshot.")}</div>
      </section>`;
    }).join("")}
  </div>`;
}

function exposureHost(ip, services) {
  const host = hostByIp(ip);
  return `<a class="link-card" href="${href(`/hosts/${encodeURIComponent(ip)}`)}">
    <div class="chips">${host ? statusDot(host.status) : ""}<strong>${escapeHtml(host ? displayName(host) : ip)}</strong><span class="small mono">${escapeHtml(ip)}</span></div>
    <div class="chips" style="margin-top:.7rem">${services.map((service) => chip(serviceName(service), `${service.proto}/${service.port}`)).join("")}</div>
  </a>`;
}

function renderAnalysis() {
  const protocols = uniqueProtocols();
  const flaggedHosts = state.hosts
    .filter((host) => analysisForHost(host).grade !== "A")
    .slice(0, 12);
  return `<div class="stack">
    <section class="hero">
      <p class="eyebrow">Daily analysis - ${escapeHtml(relativeTime(state.status.last_scan))}</p>
      <h1>A small, honest read of the network.</h1>
      <p>${aiAnalysisReady() ? "This view is using the latest generated AI analysis, with deterministic local fallback still available." : "This view is derived locally from the rendered Porchlight snapshot. Enable AI analysis in Settings for generated summaries."}</p>
    </section>
    ${analysisCard(analysisForEnvironment())}
    ${renderIrregularitiesSection(12)}
    <section class="section">
      ${sectionHead("Per protocol", "How each protocol is doing", `${protocols.length} grouped`)}
      <div class="grid two">${protocols.map((item) => {
        const analysis = analysisForProtocol(item.name);
        return `<a class="link-card" href="${href(`/protocols/${encodeURIComponent(item.name)}`)}">
          <div class="chips">${chip(item.name)}<span class="grade" style="width:2rem;height:2rem;font-size:1rem;--grade-color:${gradeColor(analysis.grade)}">${analysis.grade}</span></div>
          <h3 style="margin-top:.8rem">${escapeHtml(analysis.headline)}</h3>
          <p class="small">${escapeHtml(analysis.summary)}</p>
        </a>`;
      }).join("")}</div>
    </section>
    <section class="section">
      ${sectionHead("Per host", "Hosts with notes this scan", `${flaggedHosts.length} of ${state.hosts.length} flagged`)}
      <div class="grid two">${flaggedHosts.map((host) => {
        const analysis = analysisForHost(host);
        return `<a class="link-card" href="${href(`/hosts/${encodeURIComponent(host.ip)}`)}">
          <div class="chips">${statusDot(host.status)}<strong>${escapeHtml(displayName(host))}</strong><span class="small mono">${escapeHtml(host.ip)}</span></div>
          <h3 style="margin-top:.8rem">${escapeHtml(analysis.headline)}</h3>
          <p class="small">${escapeHtml(analysis.summary)}</p>
        </a>`;
      }).join("") || empty("No flagged hosts in this snapshot.")}</div>
    </section>
  </div>`;
}

function renderSettings() {
  const setup = state.setupStatus.setup || {};
  const mqtt = state.setupStatus.mqtt || {};
  const openai = state.setupStatus.openai || {};
  const wifi = state.setupStatus.wifi || {};
  const setupMode = setup.appliance_mode && !setup.setup_complete;
  const networks = Array.isArray(wifi.networks) ? wifi.networks : [];
  const wifiNetworkOptions = networks
    .map((network) => `<option value="${escapeHtml(network.ssid)}">${escapeHtml(network.ssid)}${network.signal == null ? "" : ` - ${escapeHtml(network.signal)}%`}${network.security ? ` - ${escapeHtml(network.security)}` : ""}</option>`)
    .join("");
  const wifiWizard = setupMode ? `<section class="hero setup-wizard">
      <p class="eyebrow">First-boot setup</p>
      <h1>Connect Porchlight to Wi-Fi.</h1>
      <p>Join your home network first. Home Assistant MQTT settings are below when you are ready.</p>
      <form class="settings-form wifi-first" id="wifi-settings">
        <label><span>Found networks</span><select name="ssid_choice"><option value="">Other or hidden SSID</option>${wifiNetworkOptions}</select></label>
        <label><span>Other or hidden SSID</span><input name="ssid" autocomplete="off"></label>
        <label><span>Password</span><input name="password" type="password" autocomplete="current-password"></label>
        <div class="form-actions">
          <button type="submit">Connect Wi-Fi</button>
          <button type="button" data-action="finish-setup">Finish setup</button>
        </div>
        <p class="form-result" id="wifi-result" role="status">${escapeHtml(wifi.message || "")}</p>
      </form>
    </section>` : "";
  const settingsHero = setupMode ? "" : `<section class="hero settings-hero">
      <p class="eyebrow">Settings</p>
      <h1>Connect Porchlight to Home Assistant.</h1>
      <p>${mqtt.enabled ? "Home Assistant MQTT discovery is enabled." : "Home Assistant MQTT discovery is disabled until broker settings are saved."}</p>
      <div class="stats">
        ${stat("MQTT", mqtt.enabled ? "Enabled" : "Disabled", mqtt.host ? `${mqtt.host}:${mqtt.port || 1883}` : "no broker", "var(--porch-sky)")}
        ${stat("Password", mqtt.password_set ? "Stored" : "Empty", "never shown after saving", "var(--porch-amber)")}
        ${stat("OpenAI", openai.api_key_set ? "Stored" : "Empty", openai.analysis_enabled ? "analysis enabled" : "analysis disabled", "var(--porch-leaf)")}
        ${stat("AI status", openai.analysis_status?.status || state.analysis.status || "missing", openai.model || "gpt-5-mini", "var(--porch-amber)")}
        ${stat("Wi-Fi", wifi.connected ? "Connected" : "Not connected", wifi.ssid || wifi.message || "setup AP available", "var(--porch-leaf)")}
        ${stat("Address", setup.mdns_name || "porchlight.local", setup.setup_ssid || "local dashboard", "var(--porch-clay)")}
      </div>
    </section>`;
  return `<div class="stack">
    ${wifiWizard}
    ${settingsHero}
    <section class="section">
      ${sectionHead("Home Assistant", "MQTT broker")}
      <form class="settings-form" id="mqtt-settings">
        <label><span>Enable discovery</span><input type="checkbox" name="enabled" ${mqtt.enabled ? "checked" : ""}></label>
        <label><span>Broker host</span><input name="host" value="${escapeHtml(mqtt.host || "")}" placeholder="homeassistant.local" autocomplete="off"></label>
        <label><span>Broker port</span><input name="port" type="number" min="1" max="65535" value="${escapeHtml(mqtt.port || 1883)}"></label>
        <label><span>Username</span><input name="username" value="${escapeHtml(mqtt.username || "")}" autocomplete="username"></label>
        <label><span>Password</span><input name="password" type="password" placeholder="${mqtt.password_set ? "Stored - leave blank to keep" : ""}" autocomplete="current-password"></label>
        <label><span>Discovery prefix</span><input name="discovery_prefix" value="${escapeHtml(mqtt.discovery_prefix || "homeassistant")}"></label>
        <label><span>Base topic</span><input name="base_topic" value="${escapeHtml(mqtt.base_topic || "porchlight")}"></label>
        <label><span>Node ID</span><input name="node_id" value="${escapeHtml(mqtt.node_id || "porchlight")}"></label>
        <label><span>Device name</span><input name="device_name" value="${escapeHtml(mqtt.device_name || "Porchlight LAN Directory")}"></label>
        <div class="form-actions">
          <button type="submit">Save MQTT</button>
          <button type="button" data-action="test-mqtt">Test publish</button>
        </div>
        <p class="form-result" id="mqtt-result" role="status"></p>
      </form>
    </section>
    <section class="section">
      ${sectionHead("OpenAI", "AI analysis")}
      <form class="settings-form" id="openai-settings">
        <label><span>Enable AI analysis</span><input type="checkbox" name="analysis_enabled" ${openai.analysis_enabled ? "checked" : ""}></label>
        <label><span>Model</span><input name="model" value="${escapeHtml(openai.model || "gpt-5-mini")}" autocomplete="off"></label>
        <label><span>Service tier</span><select name="service_tier">
          ${["flex", "auto", "default", "priority"].map((tier) => `<option value="${tier}" ${tier === (openai.service_tier || "flex") ? "selected" : ""}>${tier}</option>`).join("")}
        </select></label>
        <label><span>API key</span><input name="api_key" type="password" placeholder="${openai.api_key_set ? "Stored - leave blank to keep" : ""}" autocomplete="off"></label>
        <p class="form-result" role="status">${escapeHtml(analysisStatusText(openai))}</p>
        <div class="form-actions">
          <button type="submit">Save AI Settings</button>
          <button type="button" data-action="run-analysis">Trigger analysis</button>
          <button type="button" data-action="clear-openai">Clear key</button>
        </div>
        <p class="form-result" id="openai-result" role="status"></p>
      </form>
    </section>
  </div>`;
}

function empty(message) {
  return `<div class="route-empty"><p class="muted">${escapeHtml(message)}</p></div>`;
}

function notFound(message) {
  return `<section class="route-empty"><h1>${escapeHtml(message)}</h1><p><a href="${href("/")}">Return to overview</a></p></section>`;
}

function render() {
  activeNav();
  const path = route();
  state.currentRoute = path;
  const app = document.querySelector("#app");
  if (path === "/") app.innerHTML = renderOverview();
  else if (path === "/hosts") app.innerHTML = renderHosts();
  else if (path.startsWith("/hosts/")) app.innerHTML = renderHostDetail(decodeURIComponent(path.slice("/hosts/".length)));
  else if (path === "/protocols") app.innerHTML = renderProtocols();
  else if (path.startsWith("/protocols/")) app.innerHTML = renderProtocolDetail(decodeURIComponent(path.slice("/protocols/".length)));
  else if (path === "/exposures") app.innerHTML = renderExposures();
  else if (path === "/analysis") app.innerHTML = renderAnalysis();
  else if (path === "/settings") app.innerHTML = renderSettings();
  else app.innerHTML = notFound("Page not found.");
  bindControls();
  app.focus({ preventScroll: true });
}

function navigateTo(nextRoute) {
  const normalized = nextRoute.startsWith("/") ? nextRoute : `/${nextRoute}`;
  if (normalized === state.currentRoute) {
    closeDrawer();
    return;
  }
  const run = () => {
    state.suppressHashRender = true;
    window.location.hash = normalized;
    render();
    closeDrawer();
    if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: "instant" });
  };
  if (document.startViewTransition) {
    document.startViewTransition(run);
  } else {
    run();
  }
}

function bindControls() {
  const search = document.querySelector("#host-search");
  if (search) {
    search.addEventListener("input", (event) => {
      state.query = event.target.value;
      render();
      const next = document.querySelector("#host-search");
      if (next) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    });
  }
  document.querySelectorAll("[data-control='status'] button").forEach((button) => {
    button.addEventListener("click", () => {
      state.statusFilter = button.dataset.value;
      render();
    });
  });
  document.querySelectorAll("[data-control='group'] button").forEach((button) => {
    button.addEventListener("click", () => {
      state.groupBy = button.dataset.value;
      render();
    });
  });
  bindSettings();
}

function formPayload(form) {
  const data = new FormData(form);
  const payload = {};
  for (const [key, value] of data.entries()) payload[key] = value;
  if (form.id === "mqtt-settings") {
    payload.enabled = form.elements.enabled.checked;
    payload.port = Number(payload.port || 1883);
    if (!payload.password) delete payload.password;
  } else if (form.id === "openai-settings") {
    payload.analysis_enabled = form.elements.analysis_enabled.checked;
    if (!payload.api_key) delete payload.api_key;
  } else if (form.id === "wifi-settings") {
    payload.ssid = String(payload.ssid_choice || payload.ssid || "").trim();
    delete payload.ssid_choice;
  }
  return payload;
}

function setResult(id, message, ok = true) {
  const node = document.querySelector(id);
  if (!node) return;
  node.textContent = message;
  node.dataset.status = ok ? "ok" : "error";
}

function bindSettings() {
  const mqtt = document.querySelector("#mqtt-settings");
  if (mqtt) {
    mqtt.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await postJson("/api/setup/mqtt", formPayload(mqtt));
        state.setupStatus.mqtt = data.mqtt || state.setupStatus.mqtt;
        setResult("#mqtt-result", "MQTT settings saved.");
      } catch (error) {
        setResult("#mqtt-result", error.message, false);
      }
    });
  }
  document.querySelector("[data-action='test-mqtt']")?.addEventListener("click", async () => {
    try {
      const data = await postJson("/api/setup/mqtt/test", mqtt ? formPayload(mqtt) : {});
      setResult("#mqtt-result", data.message || "Test publish sent.");
    } catch (error) {
      setResult("#mqtt-result", error.message, false);
    }
  });
  const openai = document.querySelector("#openai-settings");
  if (openai) {
    openai.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await postJson("/api/setup/openai", formPayload(openai));
        state.setupStatus.openai = data.openai || state.setupStatus.openai;
        if (openai.elements.api_key) openai.elements.api_key.value = "";
        setResult("#openai-result", "AI settings saved.");
      } catch (error) {
        setResult("#openai-result", error.message, false);
      }
    });
  }
  document.querySelector("[data-action='clear-openai']")?.addEventListener("click", async () => {
    try {
      const data = await postJson("/api/setup/openai", { api_key: "" });
      state.setupStatus.openai = data.openai || state.setupStatus.openai;
      if (openai?.elements?.api_key) openai.elements.api_key.value = "";
      setResult("#openai-result", "OpenAI key cleared.");
    } catch (error) {
      setResult("#openai-result", error.message, false);
    }
  });
  document.querySelector("[data-action='run-analysis']")?.addEventListener("click", async () => {
    setResult("#openai-result", "Starting AI analysis...");
    try {
      const data = await postJson("/api/setup/openai/analyze", {});
      state.setupStatus.openai = data.openai || state.setupStatus.openai;
      render();
      setResult("#openai-result", data.message || "AI analysis queued.");
    } catch (error) {
      setResult("#openai-result", error.message, false);
    }
  });
  const wifi = document.querySelector("#wifi-settings");
  if (wifi) {
    wifi.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const data = await postJson("/api/setup/wifi", formPayload(wifi));
        state.setupStatus.wifi = data.wifi || state.setupStatus.wifi;
        setResult("#wifi-result", "Wi-Fi settings submitted.");
      } catch (error) {
        setResult("#wifi-result", error.message, false);
      }
    });
  }
  document.querySelector("[data-action='finish-setup']")?.addEventListener("click", async () => {
    try {
      const data = await postJson("/api/setup/finish", {});
      state.setupStatus.setup = data.setup || state.setupStatus.setup;
      setResult("#wifi-result", "Setup complete.");
      render();
    } catch (error) {
      setResult("#wifi-result", error.message, false);
    }
  });
}

window.addEventListener("hashchange", () => {
  if (state.suppressHashRender) {
    state.suppressHashRender = false;
    return;
  }
  render();
});

load()
  .then(() => {
    bindChrome();
    render();
  })
  .catch((error) => {
    document.querySelector("#app").innerHTML = `<section class="error"><h1>Dashboard could not load.</h1><p>${escapeHtml(error.message)}</p></section>`;
  });
