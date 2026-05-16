import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "src" / "porchlight-scan"


class ScanTest(unittest.TestCase):
    def test_scan_writes_lan_and_tailscale_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.write_command(
                bin_dir / "ip",
                r'''
                import json
                import sys

                args = sys.argv[1:]
                if args == ["-j", "route", "show", "default"]:
                    print(json.dumps([{"dst": "default", "gateway": "192.168.16.1", "dev": "wlan0"}]))
                elif args == ["-j", "addr", "show"]:
                    print(json.dumps([
                        {"ifname": "wlan0", "addr_info": [
                            {"family": "inet", "local": "192.168.17.211", "prefixlen": 22}
                        ]}
                    ]))
                elif args == ["-j", "neigh", "show"]:
                    print(json.dumps([
                        {"dst": "192.168.17.100", "dev": "wlan0", "lladdr": "ec:b5:fa:84:3b:e9", "state": ["REACHABLE"]},
                        {"dst": "192.168.16.10", "dev": "wlan0", "state": ["FAILED"]},
                        {"dst": "fe80::1", "dev": "wlan0", "lladdr": "00:00:00:00:00:01", "state": ["STALE"]}
                    ]))
                else:
                    raise SystemExit(2)
                ''',
            )
            self.write_command(
                bin_dir / "tailscale",
                r'''
                import json
                import sys

                if sys.argv[1:] != ["status", "--json"]:
                    raise SystemExit(2)
                print(json.dumps({
                    "Self": {
                        "HostName": "thalia",
                        "DNSName": "thalia.example.ts.net.",
                        "OS": "linux",
                        "Online": True,
                        "TailscaleIPs": ["100.70.232.78"]
                    },
                    "Peer": {
                        "nodekey:1": {
                            "HostName": "calliope",
                            "DNSName": "calliope.example.ts.net.",
                            "OS": "linux",
                            "Online": True,
                            "TailscaleIPs": ["100.98.113.100"]
                        }
                    }
                }))
                ''',
            )

            env = os.environ.copy()
            env["MUSTER_MOCK_ROOT"] = str(root)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

            result = subprocess.run(
                [str(SCAN), "--mode", "scan"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            status = json.loads((root / "run/porchlight/status.json").read_text())
            inventory = json.loads((root / "var/lib/porchlight/www/hosts.json").read_text())

            self.assertEqual(status["network_cidr"], "192.168.16.0/22")
            self.assertEqual(status["gateway"], "192.168.16.1")
            self.assertEqual(status["hosts_seen"], 4)
            self.assertEqual(status["active_hosts"], 3)
            self.assertEqual(status["sources"]["lan_neighbor_count"], 2)
            self.assertEqual(status["sources"]["tailscale_count"], 2)
            self.assertIn("100.98.113.100", {host["ip"] for host in inventory["hosts"]})
            self.assertIn("192.168.17.100", {host["ip"] for host in inventory["hosts"]})

    def write_command(self, path, body):
        path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body).strip() + "\n")
        path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
