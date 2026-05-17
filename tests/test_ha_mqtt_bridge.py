import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "src" / "porchlight-ha-mqtt-bridge"


class HomeAssistantMqttBridgeTest(unittest.TestCase):
    def run_bridge(self, mock_root, *args, extra_env=None, expect_ok=True):
        env = os.environ.copy()
        env["MUSTER_MOCK_ROOT"] = str(mock_root)
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [str(BRIDGE), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        if expect_ok and result.returncode != 0:
            self.fail(f"bridge failed\nstdout={result.stdout}\nstderr={result.stderr}")
        return result

    def test_mock_first_discovery_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run/porchlight").mkdir(parents=True)
            (root / "run/muster").mkdir(parents=True)
            (root / "var/lib/porchlight/www").mkdir(parents=True)
            (root / "run/porchlight/status.json").write_text(
                json.dumps(
                    {
                        "health": "healthy",
                        "scan_state": "idle",
                        "last_scan": "2026-05-16T13:15:02-05:00",
                        "network_cidr": "192.168.1.0/24",
                        "gateway": "192.168.1.1",
                        "hosts_seen": 42,
                        "active_hosts": 31,
                        "open_ports": 88,
                        "http_services": 9,
                        "rtsp_services": 2,
                        "mqtt_services": 1,
                        "internal_services": 12,
                        "new_hosts": 2,
                        "changed_services": 4,
                        "changes_detected": True,
                    }
                )
            )

            self.run_bridge(root, "--once")

            outbox = root / "run/muster/home-assistant-mqtt-bridge/mqtt-outbox"
            discovery = json.loads((outbox / "homeassistant_device_porchlight_config.json").read_text())
            state = json.loads((outbox / "porchlight_state.json").read_text())

            self.assertEqual(discovery["device"]["name"], "Porchlight LAN Directory")
            self.assertIn("changes_detected", discovery["components"])
            self.assertIn("http_services", discovery["components"])
            self.assertIn("rtsp_services", discovery["components"])
            self.assertIn("mqtt_services", discovery["components"])
            self.assertIn("deep_scan", discovery["components"])
            self.assertEqual(state["health"], "healthy")
            self.assertEqual(state["hosts_seen"], 42)
            self.assertEqual(state["http_services"], 9)
            self.assertEqual(state["rtsp_services"], 2)
            self.assertEqual(state["mqtt_services"], 1)
            self.assertEqual(state["changes_detected"], "ON")
            self.assertEqual((outbox / "porchlight_availability.json").read_text().strip(), "online")
            topics = (outbox / "topics.log").read_text()
            self.assertIn("homeassistant/device/porchlight/config", topics)
            self.assertIn("retain=1", topics)

    def test_controls_are_allowlisted_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "run/muster/home-assistant-mqtt-bridge/mqtt-control"
            control.mkdir(parents=True)
            (control / "scan_now.cmd").write_text("PRESS\n")
            (control / "enabled.cmd").write_text("OFF\n")

            self.run_bridge(root, "--control")

            self.assertTrue((control / "scan_now.cmd.processed").exists())
            self.assertTrue((control / "enabled.cmd.processed").exists())
            self.assertEqual((root / "etc/porchlight/enabled").read_text().strip(), "false")
            actions = (control / "control-actions.log").read_text()
            self.assertIn("systemctl start porchlight-scan.service", actions)

            (control / "enabled.cmd").write_text("systemctl restart anything\n")
            self.run_bridge(root, "--control")
            self.assertTrue((control / "enabled.cmd.rejected").exists())
            result = json.loads((root / "run/muster/home-assistant-mqtt-bridge/mqtt-outbox/porchlight_control_result.json").read_text())
            self.assertEqual(result["status"], "rejected")

    def test_apply_publish_failure_keeps_mock_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "CONFIG_FILE": str(root / "missing.env"),
                "MQTT_CONFIG_FILE": str(root / "mqtt.env"),
                "PORCHLIGHT_STATE_DIR": str(root / "run/porchlight"),
                "MUSTER_STATE_DIR": str(root / "run/muster"),
                "PORCHLIGHT_WWW_DIR": str(root / "var/lib/porchlight/www"),
                "PORCHLIGHT_CONFIG_DIR": str(root / "etc/porchlight"),
                "HA_BRIDGE_RUNTIME_DIR": str(root / "run/muster/home-assistant-mqtt-bridge"),
                "HA_BRIDGE_STATE_DIR": str(root / "var/lib/muster/home-assistant-mqtt-bridge"),
                "HA_MQTT_ENABLE": "1",
                "MOSQUITTO_PUB": str(root / "missing-mosquitto-pub"),
            }
            result = self.run_bridge(root, "--apply", "--once", extra_env=env, expect_ok=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mqtt publish failed", result.stderr)
            self.assertTrue((root / "run/muster/home-assistant-mqtt-bridge/mqtt-outbox/porchlight_state.json").exists())


class MusterLifecycleTest(unittest.TestCase):
    def test_staged_install_doctor_and_uninstall_preserve_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            env = os.environ.copy()
            env["MUSTER_ROOT"] = str(stage)

            install = subprocess.run(
                [str(ROOT / "bin/install.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(install.returncode, 0, install.stderr)

            version = (ROOT / "VERSION").read_text().strip()
            current = stage / "opt/porchlight/current"
            self.assertTrue(current.exists())
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/bin/porchlight-ha-mqtt-bridge").is_file())
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/bin/porchlight-scan").is_file())
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/systemd/porchlight-scan.service").is_file())
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/systemd/porchlight-scan.timer").is_file())
            self.assertTrue((stage / "etc/porchlight/porchlight.env").is_file())
            self.assertTrue((stage / "etc/porchlight/porchlight.mqtt.env").is_file())
            self.assertEqual((stage / "etc/porchlight/enabled").read_text().strip(), "true")

            doctor = subprocess.run(
                [str(ROOT / "bin/doctor.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertIn("PASS bridge emits state", doctor.stdout)

            uninstall = subprocess.run(
                [str(ROOT / "bin/uninstall.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertFalse(current.exists())
            self.assertTrue((stage / "etc/porchlight/porchlight.env").is_file())
            self.assertTrue((stage / "etc/porchlight/porchlight.mqtt.env").is_file())

            install_again = subprocess.run(
                [str(ROOT / "bin/install.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(install_again.returncode, 0, install_again.stderr)

            purge = subprocess.run(
                [str(ROOT / "bin/uninstall.sh"), "--purge"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(purge.returncode, 0, purge.stderr)
            self.assertFalse((stage / "etc/porchlight").exists())

    def test_staged_appliance_install_adds_setup_assets_without_purging_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            env = os.environ.copy()
            env["MUSTER_ROOT"] = str(stage)

            install = subprocess.run(
                [str(ROOT / "bin/install.sh"), "--appliance"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(install.returncode, 0, install.stderr)

            version = (ROOT / "VERSION").read_text().strip()
            current = stage / "opt/porchlight/current"
            setup_env = stage / "etc/porchlight/setup.env"
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/bin/setup-ap.sh").is_file())
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/bin/setup-apply.sh").is_file())
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/systemd/porchlight-setup-ap.service").is_file())
            self.assertTrue((stage / f"opt/porchlight/releases/{version}/systemd/porchlight-setup-apply.path").is_file())
            self.assertIn("PORCHLIGHT_APPLIANCE_MODE=1", setup_env.read_text(encoding="utf-8"))

            uninstall = subprocess.run(
                [str(ROOT / "bin/uninstall.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertFalse(current.exists())
            self.assertTrue(setup_env.is_file())


if __name__ == "__main__":
    unittest.main()
