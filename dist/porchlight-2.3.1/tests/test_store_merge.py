import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.store import Store


class StoreMergeTest(unittest.TestCase):
    def test_hosts_and_services_are_merged_into_sqlite_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "porchlight.db", root / "events.ndjson")
            at = "2026-05-16T15:00:00Z"

            store.upsert_host(
                {
                    "ip": "192.168.17.100",
                    "mac": "ec:b5:fa:84:3b:e9",
                    "hostname": "printer",
                    "interface": "wlan0",
                    "active": True,
                    "sources": ["lan-neighbor"],
                },
                at,
            )
            store.upsert_service(
                {
                    "ip": "192.168.17.100",
                    "proto": "tcp",
                    "port": 22,
                    "state": "open",
                    "service_name": "ssh",
                    "product": "OpenSSH",
                    "version": "9.2p1",
                    "category": "internal",
                    "source": "nmap",
                },
                at,
            )

            hosts = store.hosts()
            services = store.services()

            self.assertEqual(len(hosts), 1)
            self.assertEqual(hosts[0]["display_name"], "printer")
            self.assertEqual(len(services), 1)
            self.assertEqual(services[0]["display_name"], "printer")
            self.assertEqual(services[0]["port"], 22)
            self.assertEqual(services[0]["category"], "internal")
            self.assertTrue((root / "events.ndjson").read_text(encoding="utf-8"))

    def test_scan_snapshots_record_irregularities_between_comparable_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "porchlight.db", root / "events.ndjson")

            first = store.start_run("scan", "2026-05-16T15:00:00Z")
            store.record_run_snapshot(
                first,
                "scan",
                [{"ip": "192.168.1.10", "stable_key": "host-a", "hostname": "alpha", "active": True}],
                [{"ip": "192.168.1.10", "proto": "tcp", "port": 22, "state": "open", "service_name": "ssh"}],
                "2026-05-16T15:00:00Z",
            )
            store.finish_run(first, "2026-05-16T15:00:01Z", "completed", 1, 1, 1)

            second = store.start_run("scan", "2026-05-16T15:05:00Z")
            irregularities = store.record_run_snapshot(
                second,
                "scan",
                [
                    {"ip": "192.168.1.10", "stable_key": "host-a", "hostname": "alpha", "active": True},
                    {"ip": "192.168.1.11", "stable_key": "host-b", "hostname": "beta", "active": True},
                ],
                [
                    {"ip": "192.168.1.10", "proto": "tcp", "port": 22, "state": "open", "service_name": "ssh"},
                    {"ip": "192.168.1.11", "proto": "tcp", "port": 80, "state": "open", "service_name": "http"},
                ],
                "2026-05-16T15:05:00Z",
            )

            kinds = {item["kind"] for item in irregularities}
            self.assertIn("host_new", kinds)
            self.assertIn("service_opened", kinds)
            self.assertEqual(len(store.recent_irregularities()), 2)

    def test_discover_snapshots_do_not_create_service_closed_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "porchlight.db", root / "events.ndjson")

            first = store.start_run("scan", "2026-05-16T15:00:00Z")
            store.record_run_snapshot(
                first,
                "scan",
                [{"ip": "192.168.1.10", "stable_key": "host-a", "hostname": "alpha", "active": True}],
                [{"ip": "192.168.1.10", "proto": "tcp", "port": 22, "state": "open", "service_name": "ssh"}],
                "2026-05-16T15:00:00Z",
            )
            store.finish_run(first, "2026-05-16T15:00:01Z", "completed", 1, 1, 1)

            discover = store.start_run("discover", "2026-05-16T15:10:00Z")
            irregularities = store.record_run_snapshot(
                discover,
                "discover",
                [{"ip": "192.168.1.10", "stable_key": "host-a", "hostname": "alpha", "active": True}],
                [],
                "2026-05-16T15:10:00Z",
            )

            self.assertEqual(irregularities, [])
            self.assertEqual(store.recent_irregularities(), [])


if __name__ == "__main__":
    unittest.main()
