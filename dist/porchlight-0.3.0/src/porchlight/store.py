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
"""


class Store:
    def __init__(self, path: Path, events_path: Path):
        self.path = path
        self.events_path = events_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

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
        for field, source in (("hostname", "observed"), ("dns_name", "tailscale")):
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
            INSERT INTO services(host_id, proto, port, service_name, product, version, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(host_id, proto, port) DO UPDATE SET
              service_name=excluded.service_name, product=excluded.product, version=excluded.version, source=excluded.source
            """,
            (host_id, service["proto"], service["port"], service.get("service_name"), service.get("product"), service.get("version"), service.get("source")),
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
                   a.ip, a.mac, a.interface
            FROM hosts h
            LEFT JOIN addresses a ON a.host_id = h.id
            ORDER BY h.last_seen_at DESC, h.display_name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def services(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT h.display_name, a.ip, p.proto, p.port, p.state, s.service_name, s.product, s.version
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
