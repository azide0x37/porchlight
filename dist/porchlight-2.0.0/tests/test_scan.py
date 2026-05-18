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
            self.write_command(
                bin_dir / "getent",
                r'''
                import sys

                if sys.argv[1:] == ["hosts", "192.168.17.100"]:
                    print("192.168.17.100 KP303")
                elif len(sys.argv) == 3 and sys.argv[1] == "hosts":
                    raise SystemExit(2)
                else:
                    raise SystemExit(2)
                ''',
            )
            self.write_command(
                bin_dir / "nmap",
                r'''
                print("""<?xml version="1.0" encoding="UTF-8"?>
                <nmaprun>
                  <host>
                    <address addr="192.168.17.100" addrtype="ipv4"/>
                    <ports>
                      <port protocol="tcp" portid="80">
                        <state state="open"/>
                        <service name="http" product="lighttpd"/>
                      </port>
                      <port protocol="tcp" portid="554">
                        <state state="open"/>
                        <service name="rtsp"/>
                      </port>
                      <port protocol="tcp" portid="1883">
                        <state state="open"/>
                        <service name="mqtt"/>
                      </port>
                    </ports>
                  </host>
                </nmaprun>""")
                ''',
            )

            env = os.environ.copy()
            env["MUSTER_MOCK_ROOT"] = str(root)
            env["PORCHLIGHT_HTTP_TITLE_TIMEOUT_SECONDS"] = "0"
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
            www = root / "var/lib/porchlight/www"

            self.assertEqual(status["network_cidr"], "192.168.16.0/22")
            self.assertEqual(status["gateway"], "192.168.16.1")
            self.assertEqual(status["hosts_seen"], 4)
            self.assertEqual(status["active_hosts"], 3)
            self.assertEqual(status["sources"]["lan_neighbor_count"], 2)
            self.assertEqual(status["sources"]["tailscale_count"], 2)
            self.assertEqual(status["sources"]["nmap_service_count"], 3)
            self.assertEqual(status["open_ports"], 3)
            self.assertEqual(status["http_services"], 1)
            self.assertEqual(status["rtsp_services"], 1)
            self.assertEqual(status["mqtt_services"], 1)
            self.assertIn("100.98.113.100", {host["ip"] for host in inventory["hosts"]})
            self.assertIn("192.168.17.100", {host["ip"] for host in inventory["hosts"]})
            self.assertIn("KP303", {host["display_name"] for host in inventory["hosts"]})
            self.assertIn("Porchlight - LAN directory", (www / "index.html").read_text(encoding="utf-8"))
            self.assertIn("/snapshot.json", (www / "app.js").read_text(encoding="utf-8"))
            self.assertTrue((www / "icon-round.png").is_file())

    def test_discover_run_preserves_last_service_inventory(self):
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
                        {"dst": "192.168.17.100", "dev": "wlan0", "lladdr": "ec:b5:fa:84:3b:e9", "state": ["REACHABLE"]}
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
                print(json.dumps({"Self": {}, "Peer": {}}))
                ''',
            )
            self.write_command(
                bin_dir / "getent",
                r'''
                import sys
                raise SystemExit(2)
                ''',
            )
            self.write_command(
                bin_dir / "nmap",
                r'''
                print("""<?xml version="1.0" encoding="UTF-8"?>
                <nmaprun>
                  <host>
                    <address addr="192.168.17.100" addrtype="ipv4"/>
                    <ports>
                      <port protocol="tcp" portid="80">
                        <state state="open"/>
                        <service name="http" product="lighttpd"/>
                      </port>
                    </ports>
                  </host>
                </nmaprun>""")
                ''',
            )

            env = os.environ.copy()
            env["MUSTER_MOCK_ROOT"] = str(root)
            env["PORCHLIGHT_HTTP_TITLE_TIMEOUT_SECONDS"] = "0"
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

            scan_result = subprocess.run(
                [str(SCAN), "--mode", "scan"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(scan_result.returncode, 0, scan_result.stderr)

            discover_result = subprocess.run(
                [str(SCAN), "--mode", "discover"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(discover_result.returncode, 0, discover_result.stderr)

            status = json.loads((root / "run/porchlight/status.json").read_text())
            services = json.loads((root / "var/lib/porchlight/www/services.json").read_text())

            self.assertEqual(status["sources"]["nmap_service_count"], 0)
            self.assertEqual(status["open_ports"], 1)
            self.assertEqual(status["http_services"], 1)
            self.assertEqual(len(services["services"]), 1)

    def write_command(self, path, body):
        path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body).strip() + "\n")
        path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
