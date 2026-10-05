from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .config import load_env_file

LIMIT = 2 * 1024 * 1024
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def age_seconds(value: str | None, now: float | None = None) -> float | None:
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        age = (time.time() if now is None else now) - date.timestamp()
        return age if age >= -5 else None
    except (AttributeError, TypeError, ValueError):
        return None


def safe_url(value: str, *, network: bool = False) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError("URL must be a string without control characters")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("only HTTP(S) URLs without credentials are permitted")
    if parsed.query or parsed.fragment:
        raise ValueError("URLs must not contain query strings or fragments")
    if not (1 <= (parsed.port or 80) <= 65535):
        raise ValueError("invalid port")
    if network:
        # Administrator-owned registry only. No URL parameters are accepted from the browser.
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 80, type=socket.SOCK_STREAM)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                raise ValueError("unsafe probe address")
            if not (ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")):
                raise ValueError("probes require a private or Tailscale address")
    return value


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url: str, *, headers=None, payload=None, timeout: float = 10, query=None) -> tuple[int, bytes]:
    safe_url(url, network=True)
    if query:
        url += "?" + urlencode(query)
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=body, headers=headers or {})
    opener = build_opener(ProxyHandler({}), NoRedirects())
    try:
        response = opener.open(req, timeout=timeout)
    except HTTPError as exc:
        # A redirect is reported as reachability, never followed with credentials.
        response = exc
    with response:
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("upstream response exceeds limit")
        return response.code, data


def read_json(url: str, **kwargs):
    status, body = request(url, **kwargs)
    if status != 200:
        raise ValueError("upstream request did not succeed")
    return json.loads(body)


def validate_links(record: dict) -> None:
    links = record.get("links", [])
    if not isinstance(links, list) or len(links) > 20:
        raise ValueError("invalid links")
    for link in links:
        if not isinstance(link, dict) or not isinstance(link.get("url"), str):
            raise ValueError("link URL must be a string")
        safe_url(link["url"])


def load_registry(path: Path) -> dict:
    if not path.is_file():
        return {"hosts": [], "services": [], "interval_seconds": 30, "stale_seconds": 120}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("registry must be an object")
    hosts = data.get("hosts", [])
    services = data.get("services", [])
    if not isinstance(hosts, list) or not isinstance(services, list) or len(hosts) > 100 or len(services) > 500:
        raise ValueError("invalid or excessive registry size")
    host_ids, service_ids = set(), set()
    for host in hosts:
        if not isinstance(host, dict):
            raise ValueError("host must be an object")
        key = host.get("id", "")
        if not isinstance(key, str):
            raise ValueError("host id must be a string")
        if not IDENTIFIER.fullmatch(key) or key in host_ids:
            raise ValueError("invalid or duplicate host id")
        host_ids.add(key)
        validate_links(host)
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("service must be an object")
        key = service.get("id", "")
        if not isinstance(key, str):
            raise ValueError("service id must be a string")
        if not IDENTIFIER.fullmatch(key) or key in service_ids or service.get("host") not in host_ids:
            raise ValueError("invalid service id or host reference")
        service_ids.add(key)
        validate_links(service)
        probe = service.get("probe", {})
        if not isinstance(probe, dict):
            raise ValueError("probe must be an object")
        if probe.get("url"):
            safe_url(probe["url"])
        if probe.get("kind", "http") not in {"http", "readiness"}:
            raise ValueError("invalid probe kind")
        if probe.get("kind") == "readiness" and not probe.get("expected_text"):
            raise ValueError("readiness probes require an expected response marker")
    interval = int(data.get("interval_seconds", 30))
    stale = int(data.get("stale_seconds", 120))
    if not 15 <= interval <= 300 or not interval * 2 <= stale <= 3600:
        raise ValueError("invalid observation interval or freshness threshold")
    return {**data, "hosts": hosts, "services": services, "interval_seconds": interval, "stale_seconds": stale}


def pct(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100:
        return round(value, 1)
    return None


def unique_match(records: list[dict], key: str | None) -> dict | None:
    matches = [record for record in records if key and key in {record.get("id"), record.get("name")}]
    return matches[0] if len(matches) == 1 else None


def public_links(record: dict) -> list[dict]:
    return [{"label": str(link.get("label", "Open")), "url": safe_url(link["url"])} for link in record.get("links", [])]


def service_probe(service: dict, origin: str) -> dict:
    result = {
        "id": service["id"], "name": str(service.get("name", service["id"])), "host": service["host"],
        "purpose": str(service.get("purpose", "")), "links": public_links(service),
        "health": "unknown", "reachability": "unknown", "maintenance": bool(service.get("maintenance")),
        "observed_at": None, "checked_at": timestamp(), "probe_origin": origin, "source": "HTTP probe",
        "deployment": None, "message": "No probe configured",
    }
    probe = service.get("probe", {})
    if not probe.get("url"):
        return result
    started = time.monotonic()
    try:
        code, body = request(probe["url"], timeout=10)
        result.update(observed_at=timestamp(), http_status=code, response_ms=round((time.monotonic() - started) * 1000))
        if 200 <= code < 400 or code in {401, 403}:
            result["reachability"] = "reachable"
            result["message"] = "HTTP reachable; application readiness unverified"
            if probe.get("kind") == "readiness" and code == 200:
                marker = str(probe["expected_text"]).encode()
                result["health"] = "healthy" if marker in body else "degraded"
                result["message"] = "Readiness check passed" if marker in body else "Readiness response did not match"
        else:
            result.update(reachability="reachable", health="degraded", message="HTTP error response")
    except (OSError, ValueError):
        result.update(reachability="unreachable", message="Probe failed from this observer")
    return result


class InfrastructureMonitor:
    def __init__(self, config_dir: Path, *, origin: str | None = None, fetch_json=read_json):
        self.config_dir = config_dir
        self.origin = origin or socket.gethostname()
        self.fetch_json = fetch_json
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._data = {"hosts": [], "services": [], "providers": {}, "generated_at": None, "stale_seconds": 120}
        self.interval = 30

    def start(self):
        self._thread = threading.Thread(target=self._run, name="infrastructure-observer", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.collect()
            except Exception:
                with self._lock:
                    self._data["collector_error"] = "Observation failed"
            self._stop.wait(self.interval)

    def _credentials(self):
        return load_env_file(self.config_dir / "infrastructure.env")

    def _beszel(self, registry, credentials):
        url, token = credentials.get("BESZEL_URL"), credentials.get("BESZEL_TOKEN")
        if not url or not token:
            return {}, {"status": "unconfigured", "observed_at": None}
        safe_url(url)
        headers = {"Authorization": token}
        systems = []
        for page in range(1, 11):
            response = self.fetch_json(url.rstrip("/") + "/api/collections/systems/records", headers=headers,
                                       query={"page": page, "perPage": 100, "fields": "id,name,status,updated"})
            systems.extend(response["items"])
            if page >= response.get("totalPages", 1):
                break
        else:
            raise ValueError("Beszel system pagination exceeds limit")
        hosts = {}
        for host in registry["hosts"]:
            system = unique_match(systems, host.get("beszel_id") or host.get("beszel_name"))
            if not system:
                continue
            stats = self.fetch_json(url.rstrip("/") + "/api/collections/system_stats/records", headers=headers,
                                    query={"perPage": 1, "sort": "-created", "filter": 'system="' + system["id"] + '"',
                                           "fields": "created,stats,type"})
            record = stats["items"][0] if stats["items"] else {}
            values = record.get("stats") or {}
            hosts[host["id"]] = {
                "status": system.get("status", "unknown"), "status_observed_at": system.get("updated"),
                "observed_at": record.get("created"), "metrics": {
                    "cpu_pct": pct(values.get("cpu")), "memory_pct": pct(values.get("mp")), "disk_pct": pct(values.get("dp")),
                }, "source": "Beszel", "sample_type": record.get("type"),
            }
        return hosts, {"status": "ok", "observed_at": timestamp()}

    def _komodo(self, registry, credentials):
        url = credentials.get("KOMODO_URL")
        key, secret = credentials.get("KOMODO_API_KEY"), credentials.get("KOMODO_API_SECRET")
        if not url or not key or not secret:
            return {}, {}, {"status": "unconfigured", "observed_at": None}
        safe_url(url)
        headers = {"x-api-key": key, "x-api-secret": secret, "Content-Type": "application/json"}
        def read(kind, params=None):
            return self.fetch_json(url.rstrip("/") + "/read", headers=headers, payload={"type": kind, "params": params or {}})
        servers, stacks = read("ListServers"), read("ListStacks")
        alerts = []
        page = 0
        for _ in range(10):
            response = read("ListAlerts", {"query": {"resolved": False}, "page": page})
            alerts.extend(response["alerts"])
            if response.get("next_page") is None:
                break
            page = response["next_page"]
        else:
            raise ValueError("Komodo alert pagination exceeds limit")
        hosts = {}
        for host in registry["hosts"]:
            server = unique_match(servers, host.get("komodo_id") or host.get("komodo_name"))
            if server:
                info = server.get("info") or {}
                state = info.get("state", "unknown")
                hosts[host["id"]] = {
                    "status": {"Ok": "up", "NotOk": "down", "Disabled": "maintenance"}.get(state, "unknown"),
                    "observed_at": timestamp(), "source": "Komodo",
                    "active_alerts": sum(1 for alert in alerts if (alert.get("target") or {}).get("id") == server.get("id")),
                }
        services = {}
        for service in registry["services"]:
            stack = unique_match(stacks, service.get("komodo_stack_id") or service.get("komodo_stack"))
            if stack:
                services[service["id"]] = {"state": (stack.get("info") or {}).get("state", "Unknown"),
                                           "observed_at": timestamp(), "source": "Komodo"}
        return hosts, services, {"status": "ok", "observed_at": timestamp()}

    def collect(self):
        try:
            registry = load_registry(self.config_dir / "infrastructure.json")
            self.interval = registry["interval_seconds"]
            credentials = self._credentials()
        except (OSError, ValueError, TypeError, KeyError):
            with self._lock:
                self._data["collector_error"] = "Registry or credential configuration is invalid"
            return
        with self._lock:
            previous = deepcopy(self._data)
        data = {"configured": bool(registry["hosts"]), "generated_at": timestamp(), "probe_origin": self.origin,
                "stale_seconds": registry["stale_seconds"], "hosts": [], "services": [], "providers": {}}
        beszel_hosts, komodo_hosts, deployments = {}, {}, {}
        for provider in ("beszel", "komodo"):
            try:
                if provider == "beszel":
                    beszel_hosts, status = self._beszel(registry, credentials)
                else:
                    komodo_hosts, deployments, status = self._komodo(registry, credentials)
                data["providers"][provider] = status
            except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                data["providers"][provider] = {"status": "error", "observed_at": previous.get("providers", {}).get(provider, {}).get("observed_at")}
        old_hosts = {host["id"]: host for host in previous["hosts"]}
        for host in registry["hosts"]:
            old = old_hosts.get(host["id"], {})
            metrics = beszel_hosts.get(host["id"]) or old.get("telemetry", {})
            management = komodo_hosts.get(host["id"]) or old.get("management", {})
            data["hosts"].append({
                "id": host["id"], "name": str(host.get("name", host["id"])), "links": public_links(host),
                "maintenance": bool(host.get("maintenance")), "telemetry": metrics, "management": management,
            })
        with ThreadPoolExecutor(max_workers=8) as executor:
            data["services"] = list(executor.map(lambda service: service_probe(service, self.origin), registry["services"]))
        old_services = {service["id"]: service for service in previous["services"]}
        for service in data["services"]:
            if not service["observed_at"]:
                service["last_success_at"] = old_services.get(service["id"], {}).get("last_success_at") or old_services.get(service["id"], {}).get("observed_at")
            else:
                service["last_success_at"] = service["observed_at"]
            service["deployment"] = deployments.get(service["id"]) or old_services.get(service["id"], {}).get("deployment")
        with self._lock:
            self._data = data

    def snapshot(self):
        with self._lock:
            data = deepcopy(self._data)
        now = time.time()
        ttl = data["stale_seconds"]
        data["collector_age_seconds"] = age_seconds(data.get("generated_at"), now)
        data["collector_stale"] = data["collector_age_seconds"] is None or data["collector_age_seconds"] > ttl or bool(data.get("collector_error"))
        for host in data["hosts"]:
            telemetry, management = host["telemetry"], host["management"]
            telemetry_age = age_seconds(telemetry.get("observed_at"), now)
            management_age = age_seconds(management.get("observed_at"), now)
            host["telemetry_stale"] = telemetry_age is None or telemetry_age > ttl
            host["management_stale"] = management_age is None or management_age > ttl
            host["status"] = "unknown"
            if not host["management_stale"]:
                host["status"] = management.get("status", "unknown")
            elif age_seconds(telemetry.get("status_observed_at"), now) is not None and age_seconds(telemetry.get("status_observed_at"), now) <= ttl:
                host["status"] = telemetry.get("status", "unknown")
            if host["maintenance"]:
                host["status"] = "maintenance"
            if data["collector_stale"]:
                host["status"] = "unknown" if not host["maintenance"] else "maintenance"
        for service in data["services"]:
            age = age_seconds(service["observed_at"], now)
            checked_age = age_seconds(service["checked_at"], now)
            service["stale"] = checked_age is None or checked_age > ttl or data["collector_stale"]
            service["sample_age_seconds"] = age
            deployment = service.get("deployment") or {}
            deployment_age = age_seconds(deployment.get("observed_at"), now)
            service["deployment_stale"] = deployment_age is None or deployment_age > ttl
            if service["stale"]:
                service["health"] = "unknown"
                service["reachability"] = "unknown"
        return data

