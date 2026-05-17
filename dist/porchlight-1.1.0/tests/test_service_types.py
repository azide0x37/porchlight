import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.service_types import service_category, service_counts, service_url


class ServiceTypesTest(unittest.TestCase):
    def test_common_service_categories_and_links(self):
        services = [
            {"ip": "192.168.16.10", "port": 80, "service_name": "http"},
            {"ip": "192.168.16.11", "port": 554, "service_name": "rtsp"},
            {"ip": "192.168.16.12", "port": 1883, "service_name": "mqtt"},
            {"ip": "192.168.16.13", "port": 22, "service_name": "ssh"},
        ]

        self.assertEqual([service_category(service) for service in services], ["http", "rtsp", "mqtt", "internal"])
        self.assertEqual(service_url(services[0]), "http://192.168.16.10/")
        self.assertEqual(service_url(services[1]), "rtsp://192.168.16.11:554/")
        self.assertEqual(
            service_counts([{**service, "category": service_category(service)} for service in services]),
            {"http_services": 1, "rtsp_services": 1, "mqtt_services": 1, "internal_services": 1},
        )


if __name__ == "__main__":
    unittest.main()
