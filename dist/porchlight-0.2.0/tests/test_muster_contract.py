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
        scan = (ROOT / "systemd/porchlight-scan.service").read_text(encoding="utf-8")
        scan_timer = (ROOT / "systemd/porchlight-scan.timer").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/opt/porchlight/current/bin/porchlight-scan --apply --mode scan", scan)
        self.assertIn("Unit=porchlight-scan.service", scan_timer)

    def test_readme_self_certifies_muster_contract(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in [
            "## Self-Certification",
            "curl -fsSL https://github.com/azide0x37/porchlight/releases/latest/download/install.sh | sudo sh",
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

    def test_release_manifest_shape_matches_dvd_ingester_reference(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for text in [
            '"project"',
            '"artifact"',
            '"artifact_url"',
            '"sha256"',
            '"installer"',
            "cp bin/install.sh",
            "releases/download/v",
        ]:
            self.assertIn(text, makefile)

    def test_installer_and_doctor_cover_mqtt_adapter_dependency(self):
        install = (ROOT / "bin/install.sh").read_text(encoding="utf-8")
        doctor = (ROOT / "bin/doctor.sh").read_text(encoding="utf-8")

        self.assertIn("mosquitto-clients", install)
        self.assertIn("MUSTER_SKIP_PACKAGES", install)
        self.assertIn("HA_MQTT_ENABLE", doctor)
        self.assertIn("mqtt publish adapter available", doctor)
