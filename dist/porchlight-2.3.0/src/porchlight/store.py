from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from .identity import display_name, stable_key
from .util import append_event


SCHEMA = """
CREATE TABLE IF NOT EXISTS hosts (
  id INTEGER PRIMARY KEY,
  stable_key TEXT NOT NULL UNIQUE,
  display_name TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  last_changed_at TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS addresses (
  host_id INTEGER NOT NULL,
  ip TEXT NOT NULL,
  mac TEXT,
  interface TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(host_id, ip)
);
CREATE TABLE IF NOT EXISTS hostnames (
  host_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.5,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(host_id, name, source)
);
CREATE TABLE IF NOT EXISTS ports (
  host_id INTEGER NOT NULL,
  ip TEXT NOT NULL,
  proto TEXT NOT NULL,
  port INTEGER NOT NULL,
  state TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  last_changed_at TEXT NOT NULL,
  UNIQUE(host_id, ip, proto, port)
);
CREATE TABLE IF NOT EXISTS services (
  host_id INTEGER NOT NULL,
  proto TEXT NOT NULL,
  port INTEGER NOT NULL,
  service_name TEXT,
  product TEXT,
  version TEXT,
  banner TEXT,
  url TEXT,
  title TEXT,
  category TEXT,
  source TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  UNIQUE(host_id, proto, port)
);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY,
  run_id INTEGER,
  observed_at TEXT NOT NULL,
  source TEXT NOT NULL,
  host_hint TEXT,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_runs (
  id INTEGER PRIMARY KEY,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  targets_count INTEGER NOT NULL DEFAULT 0,
  hosts_seen INTEGER NOT NULL DEFAULT 0,
  ports_open INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
CREATE TABLE IF NOT EXISTS run_hosts (
  run_id INTEGER NOT NULL,
  stable_key TEXT NOT NULL,
  ip TEXT NOT NULL,
  display_name TEXT,
  status TEXT NOT NULL,
  active INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(run_id, stable_key, ip)
);
CREATE TABLE IF NOT EXISTS run_services (
  run_id INTEGER NOT NULL,
  ip TEXT NOT NULL,
  proto TEXT NOT NULL,
  port INTEGER NOT NULL,
  service_name TEXT,
  product TEXT,
  version TEXT,
  title TEXT,
  category TEXT,
  payload_json TEXT NOT NULL,
  UNIQUE(run_id, ip, proto, port)
);
CREATE TABLE IF NOT EXISTS irregularities (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  subject_key TEXT,
  payload_json TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path, events_path: Path):
        self.path = path
        self.events_path = events_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.migrate()
        self.conn.commit()

    def migrate(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(services)").fetchall()}
        for column in ("url", "title", "category"):
            if column not in columns:
                self.conn.execute(f"ALTER TABLE services ADD COLUMN {column} TEXT")

    def start_run(self, mode: str, started_at: str) -> int:
        cursor = self.conn.execute("INSERT INTO scan_runs(mode, started_at, status) VALUES (?, ?, ?)", (mode, started_at, "running"))
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, finished_at: str, status: str, targets_count: int, hosts_seen: int, ports_open: int, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE scan_runs SET finished_at=?, status=?, targets_count=?, hosts_seen=?, ports_open=?, error=? WHERE id=?",
            (finished_at, status, targets_count, hosts_seen, ports_open, error, run_id),
        )
        self.conn.commit()

    def record_run_snapshot(self, run_id: int, mode: str, hosts: list[dict], services: list[dict], observed_at: str) -> list[dict]:
        host_rows = []
        for host in hosts:
            key = str(host.get("stable_key") or stable_key(host))
            status = "active" if host.get("active") else "inactive"
            host_rows.append(
                (
                    run_id,
                    key,
                    host.get("ip", ""),
                    display_name(host),
                    status,
                    1 if host.get("active") else 0,
                    json.dumps(host, sort_keys=True),
                )
            )
        service_rows = [
            (
                run_id,
                service.get("ip", ""),
                service.get("proto", ""),
                int(service.get("port") or 0),
                service.get("service_name"),
                service.get("product"),
                service.get("version"),
                service.get("title"),
                service.get("category"),
                json.dumps(service, sort_keys=True),
            )
            for service in services
        ]
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO run_hosts(run_id, stable_key, ip, display_name, status, active, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            host_rows,
        )
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO run_services(run_id, ip, proto, port, service_name, product, version, title, category, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            service_rows,
        )
        irregularities = self._diff_against_previous_run(run_id, mode, observed_at)
        self.conn.commit()
        return irregularities

    def _diff_against_previous_run(self, run_id: int, mode: str, observed_at: str) -> list[dict]:
        if mode not in {"scan", "deep"}:
            return []
        previous = self.conn.execute(
            """
            SELECT id FROM scan_runs
            WHERE mode=? AND status='completed' AND id < ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (mode, run_id),
        ).fetchone()
        if not previous:
            return []

        previous_hosts = self._run_hosts(int(previous["id"]))
        current_hosts = self._run_hosts(run_id)
        previous_services = self._run_services(int(previous["id"]))
        current_services = self._run_services(run_id)
        irregularities: list[dict] = []

        previous_active = {key: value for key, value in previous_hosts.items() if value.get("active")}
        current_active = {key: value for key, value in current_hosts.items() if value.get("active")}
        for key in sorted(current_active.keys() - previous_active.keys()):
            host = current_active[key]
            irregularities.append(
                self._irregularity(
                    run_id,
                    observed_at,
                    "host_new",
                    "notice",
                    "New active host",
                    f"{host['display_name']} ({host['ip']}) appeared in this scan.",
                    key,
                    host,
                )
            )
        for key in sorted(previous_active.keys() - current_active.keys()):
            host = previous_active[key]
            irregularities.append(
                self._irregularity(
                    run_id,
                    observed_at,
                    "host_missing",
                    "warning",
                    "Previously active host missing",
                    f"{host['display_name']} ({host['ip']}) did not appear in this scan.",
                    key,
                    host,
                )
            )

        for key in sorted(current_services.keys() - previous_services.keys()):
            service = current_services[key]
            irregularities.append(
                self._irregularity(
                    run_id,
                    observed_at,
                    "service_opened",
                    "warning",
                    "Service opened",
                    f"{service['ip']} now answers on {service['proto']}/{service['port']} {service.get('service_name') or 'unknown'}.",
                    self._service_subject(service),
                    service,
                )
            )
        for key in sorted(previous_services.keys() - current_services.keys()):
            service = previous_services[key]
            irregularities.append(
                self._irregularity(
                    run_id,
                    observed_at,
                    "service_closed",
                    "notice",
                    "Service no longer visible",
                    f"{service['ip']} no longer answers on {service['proto']}/{service['port']} {service.get('service_name') or 'unknown'}.",
                    self._service_subject(service),
                    service,
                )
            )
        for key in sorted(current_services.keys() & previous_services.keys()):
            current = current_services[key]
            previous_service = previous_services[key]
            changed_fields = [
                field
                for field in ("service_name", "product", "version", "title", "category")
                if (current.get(field) or "") != (previous_service.get(field) or "")
            ]
            if changed_fields:
                payload = {"current": current, "previous": previous_service, "changed_fields": changed_fields}
                irregularities.append(
                    self._irregularity(
                        run_id,
                        observed_at,
                        "service_changed",
                        "notice",
                        "Service metadata changed",
                        f"{current['ip']} {current['proto']}/{current['port']} changed {', '.join(changed_fields)}.",
                        self._service_subject(current),
                        payload,
                    )
                )

        self._insert_irregularities(irregularities)
        return irregularities

    def _run_hosts(self, run_id: int) -> dict[str, dict]:
        rows = self.conn.execute("SELECT * FROM run_hosts WHERE run_id=?", (run_id,)).fetchall()
        return {
            row["stable_key"]: {
                "stable_key": row["stable_key"],
                "ip": row["ip"],
                "display_name": row["display_name"],
                "status": row["status"],
                "active": bool(row["active"]),
            }
            for row in rows
        }

    def _run_services(self, run_id: int) -> dict[tuple[str, str, int], dict]:
        rows = self.conn.execute("SELECT * FROM run_services WHERE run_id=?", (run_id,)).fetchall()
        return {
            (row["ip"], row["proto"], int(row["port"])): {
                "ip": row["ip"],
                "proto": row["proto"],
                "port": int(row["port"]),
                "service_name": row["service_name"],
                "product": row["product"],
                "version": row["version"],
                "title": row["title"],
                "category": row["category"],
            }
            for row in rows
        }

    def _insert_irregularities(self, irregularities: list[dict]) -> None:
        self.conn.executemany(
            """
            INSERT INTO irregularities(run_id, observed_at, kind, severity, title, summary, subject_key, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["run_id"],
                    item["observed_at"],
                    item["kind"],
                    item["severity"],
                    item["title"],
                    item["summary"],
                    item.get("subject_key"),
                    json.dumps(item.get("payload", {}), sort_keys=True),
                )
                for item in irregularities
            ],
        )

    def _irregularity(
        self,
        run_id: int,
        observed_at: str,
        kind: str,
        severity: str,
        title: str,
        summary: str,
        subject_key: str,
        payload: dict,
    ) -> dict:
        return {
            "run_id": run_id,
            "observed_at": observed_at,
            "kind": kind,
            "severity": severity,
            "title": title,
            "summary": summary,
            "subject_key": subject_key,
            "payload": payload,
        }

    def _service_subject(self, service: dict) -> str:
        return f"{service.get('ip')}:{service.get('proto')}/{service.get('port')}"

    def upsert_host(self, host: dict, observed_at: str) -> int:
        key = host.get("stable_key") or stable_key(host)
        existing = self.conn.execute("SELECT id FROM hosts WHERE stable_key=?", (key,)).fetchone()
        name = display_name(host)
        status = "active" if host.get("active") else "inactive"
        if existing:
            host_id = int(existing["id"])
            self.conn.execute(
                "UPDATE hosts SET display_name=?, last_seen_at=?, status=? WHERE id=?",
                (name, observed_at, status, host_id),
            )
        else:
            cursor = self.conn.execute(
                "INSERT INTO hosts(stable_key, display_name, first_seen_at, last_seen_at, last_changed_at, status) VALUES (?, ?, ?, ?, ?, ?)",
                (key, name, observed_at, observed_at, observed_at, status),
            )
            host_id = int(cursor.lastrowid)
            append_event(self.events_path, {"event": "host_first_seen", "at": observed_at, "stable_key": key, "ip": host.get("ip")})
        self._upsert_address(host_id, host, observed_at)
        for field, source in (("hostname", "observed"), ("dns_name", "tailscale"), ("reverse_dns", "reverse_dns")):
            if host.get(field):
                self._upsert_hostname(host_id, host[field], source, observed_at)
        self.conn.execute(
            "INSERT INTO observations(observed_at, source, host_hint, payload_json) VALUES (?, ?, ?, ?)",
            (observed_at, ",".join(host.get("sources", [])), host.get("ip"), json.dumps(host, sort_keys=True)),
        )
        self.conn.commit()
        return host_id

    def upsert_service(self, service: dict, observed_at: str) -> None:
        host_row = self.conn.execute("SELECT host_id FROM addresses WHERE ip=? ORDER BY last_seen_at DESC LIMIT 1", (service["ip"],)).fetchone()
        if not host_row:
            host_id = self.upsert_host({"ip": service["ip"], "active": True, "source": "nmap"}, observed_at)
        else:
            host_id = int(host_row["host_id"])
        self.conn.execute(
            """
            INSERT INTO ports(host_id, ip, proto, port, state, first_seen_at, last_seen_at, last_changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(host_id, ip, proto, port) DO UPDATE SET state=excluded.state, last_seen_at=excluded.last_seen_at
            """,
            (host_id, service["ip"], service["proto"], service["port"], service["state"], observed_at, observed_at, observed_at),
        )
        self.conn.execute(
            """
            INSERT INTO services(host_id, proto, port, service_name, product, version, url, title, category, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(host_id, proto, port) DO UPDATE SET
              service_name=excluded.service_name,
              product=excluded.product,
              version=excluded.version,
              url=excluded.url,
              title=excluded.title,
              category=excluded.category,
              source=excluded.source
            """,
            (
                host_id,
                service["proto"],
                service["port"],
                service.get("service_name"),
                service.get("product"),
                service.get("version"),
                service.get("url"),
                service.get("title"),
                service.get("category"),
                service.get("source"),
            ),
        )
        self.conn.commit()

    def _upsert_address(self, host_id: int, host: dict, observed_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO addresses(host_id, ip, mac, interface, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(host_id, ip) DO UPDATE SET mac=excluded.mac, interface=excluded.interface, last_seen_at=excluded.last_seen_at
            """,
            (host_id, host["ip"], host.get("mac"), host.get("interface"), observed_at, observed_at),
        )

    def _upsert_hostname(self, host_id: int, name: str, source: str, observed_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO hostnames(host_id, name, source, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(host_id, name, source) DO UPDATE SET last_seen_at=excluded.last_seen_at
            """,
            (host_id, name, source, observed_at, observed_at),
        )

    def hosts(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT h.id, h.stable_key, h.display_name, h.first_seen_at, h.last_seen_at, h.status,
                   a.ip, a.mac, a.interface,
                   GROUP_CONCAT(hn.name, ', ') AS names
            FROM hosts h
            LEFT JOIN addresses a ON a.host_id = h.id
            LEFT JOIN hostnames hn ON hn.host_id = h.id
            GROUP BY h.id, a.ip
            ORDER BY h.last_seen_at DESC, h.display_name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def services(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT h.display_name, a.ip, p.proto, p.port, p.state, s.service_name, s.product, s.version,
                   s.url, s.title, s.category
            FROM ports p
            JOIN hosts h ON h.id = p.host_id
            LEFT JOIN addresses a ON a.host_id = h.id AND a.ip = p.ip
            LEFT JOIN services s ON s.host_id = h.id AND s.proto = p.proto AND s.port = p.port
            ORDER BY p.port, h.display_name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def recent_runs(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def recent_irregularities(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM irregularities ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            items.append(item)
        return items
