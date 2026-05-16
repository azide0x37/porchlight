from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MusterContractTest(unittest.TestCase):
    def test_systemd_units_call_current_release_bin(self):
        service = (ROOT / "systemd/porchlight-ha-mqtt-bridge.service").read_text(encoding="utf-8")
        timer = (ROOT / "systemd/porchlight-ha-mqtt-bridge.timer").read_text(encoding="utf-8")

        self.assertIn("ExecStart=/opt/porchlight/current/bin/porchlight-ha-mqtt-bridge --apply --once", service)
        self.assertIn("EnvironmentFile=-/etc/porchlight/porchlight.env", service)
        self.assertIn("EnvironmentFile=-/etc/porchlight/porchlight.mqtt.env", service)
        self.assertIn("Unit=porchlight-ha-mqtt-bridge.service", timer)

    def test_readme_self_certifies_muster_contract(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in [
            "## Self-Certification",
            "systemd owns lifecycle",
            "runtime under `/opt/porchlight/releases/<version>`",
            "updater verifies and rolls back",
            "make test",
            "make package",
        ]:
            self.assertIn(text, readme)

    def test_muster_yaml_names_lifecycle_artifacts(self):
        muster = (ROOT / "muster.yaml").read_text(encoding="utf-8")
        for text in [
            "T2R6.home-assistant-mqtt-bridge",
            "bin/install.sh",
            "bin/update.sh",
            "bin/uninstall.sh",
            "bin/doctor.sh",
            "make package",
        ]:
            self.assertIn(text, muster)
