from __future__ import annotations

from pathlib import Path
from .config import Config
from .store import Store
from .util import read_json, write_json


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Porchlight</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <h1>Porchlight</h1>
    <p id="summary">Loading network inventory...</p>
  </header>
  <main>
    <section>
      <h2>Hosts</h2>
      <table id="hosts"><thead><tr><th>Name</th><th>IP</th><th>Names</th><th>MAC</th><th>Status</th><th>Interface</th></tr></thead><tbody></tbody></table>
    </section>
    <section>
      <h2>Services</h2>
      <table id="services"><thead><tr><th>Host</th><th>IP</th><th>Port</th><th>Type</th><th>Service</th><th>Link</th><th>Product</th></tr></thead><tbody></tbody></table>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""

APP_JS = """async function loadJson(path) {
  const response = await fetch(path, {cache: "no-store"});
  return response.json();
}
function row(cells) {
  const tr = document.createElement("tr");
  for (const value of cells) {
    const td = document.createElement("td");
    if (value instanceof Node) {
      td.appendChild(value);
    } else {
      td.textContent = value == null ? "" : value;
    }
    tr.appendChild(td);
  }
  return tr;
}
function link(service) {
  if (!service.url) return "";
  const a = document.createElement("a");
  a.href = service.url;
  a.textContent = service.title || service.url;
  a.target = "_blank";
  a.rel = "noreferrer";
  return a;
}
async function main() {
  const [status, hosts, services] = await Promise.all([
    loadJson("/status.json"),
    loadJson("/hosts.json"),
    loadJson("/services.json"),
  ]);
  document.querySelector("#summary").textContent =
    `${status.hosts_seen || 0} hosts, ${status.active_hosts || 0} active, ${status.open_ports || 0} open ports, ${status.http_services || 0} HTTP, ${status.rtsp_services || 0} RTSP, ${status.mqtt_services || 0} MQTT`;
  const hostBody = document.querySelector("#hosts tbody");
  for (const host of hosts.hosts || []) {
    hostBody.appendChild(row([host.display_name || host.hostname || "", host.ip, host.names, host.mac, host.status || (host.active ? "active" : "inactive"), host.interface]));
  }
  const serviceBody = document.querySelector("#services tbody");
  for (const service of services.services || []) {
    serviceBody.appendChild(row([service.display_name, service.ip, `${service.proto}/${service.port}`, service.category, service.service_name, link(service), service.product]));
  }
}
main().catch((error) => {
  document.querySelector("#summary").textContent = error.message;
});
"""

STYLE_CSS = """body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f7f7f5;color:#1d2525}header{padding:24px 28px;background:#12343b;color:#fff}h1{margin:0 0 4px;font-size:28px}main{padding:24px 28px;display:grid;gap:28px}section{overflow:auto}table{border-collapse:collapse;width:100%;background:white;border:1px solid #d8dedb}th,td{padding:8px 10px;border-bottom:1px solid #e7ece9;text-align:left;font-size:14px}th{background:#edf3f0}tr:hover td{background:#f6faf8}"""


def render(config: Config, store: Store) -> dict:
    config.www_dir.mkdir(parents=True, exist_ok=True)
    status = read_json(config.state_dir / "status.json")
    hosts = {"hosts": store.hosts()}
    services = {"services": store.services()}
    changes = {"recent_runs": store.recent_runs()}
    snapshot = {"status": status, "hosts": hosts["hosts"], "services": services["services"], "changes": changes}

    write_json(config.www_dir / "status.json", status)
    write_json(config.www_dir / "hosts.json", hosts)
    write_json(config.www_dir / "services.json", services)
    write_json(config.www_dir / "changes.json", changes)
    write_json(config.www_dir / "snapshot.json", snapshot)
    write_static(config.www_dir)
    return snapshot


def write_static(www_dir: Path) -> None:
    (www_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (www_dir / "app.js").write_text(APP_JS, encoding="utf-8")
    (www_dir / "style.css").write_text(STYLE_CSS, encoding="utf-8")
