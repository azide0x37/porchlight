from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.discover import parse_arp_scan
from porchlight.nmap_xml import parse_nmap_xml


class ParserTest(unittest.TestCase):
    def test_nmap_xml_parser_returns_normalized_services(self):
        services = parse_nmap_xml((ROOT / "tests/fixtures/nmap-basic.xml").read_text(encoding="utf-8"))

        self.assertEqual(len(services), 2)
        self.assertEqual(services[0]["ip"], "192.168.17.100")
        self.assertEqual(services[0]["hostname"], "printer.local")
        self.assertEqual(services[0]["proto"], "tcp")
        self.assertEqual(services[0]["port"], 22)
        self.assertEqual(services[0]["state"], "open")
        self.assertEqual(services[0]["service_name"], "ssh")
        self.assertEqual(services[0]["product"], "OpenSSH")

    def test_arp_scan_parser_returns_lan_hosts(self):
        hosts = parse_arp_scan((ROOT / "tests/fixtures/arp-scan.txt").read_text(encoding="utf-8"))

        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0]["ip"], "192.168.17.100")
        self.assertEqual(hosts[0]["mac"], "ec:b5:fa:84:3b:e9")
        self.assertTrue(hosts[0]["active"])
        self.assertEqual(hosts[0]["source"], "arp-scan")


if __name__ == "__main__":
    unittest.main()
