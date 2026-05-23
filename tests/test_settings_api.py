import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.settings import (
    atomic_write_env,
    masked_mqtt_settings,
    masked_openai_settings,
    split_nmcli_fields,
    update_mqtt_settings,
    update_openai_settings,
    wifi_networks,
)


class SettingsFileTest(unittest.TestCase):
    def test_mqtt_discovery_defaults_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            masked = masked_mqtt_settings(Path(tmp))
            self.assertTrue(masked["enabled"])

    def test_mqtt_update_preserves_unknown_keys_and_masks_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            mqtt_env = config_dir / "porchlight.mqtt.env"
            mqtt_env.write_text("CUSTOM_FLAG=keep\nMQTT_PASSWORD=old-secret\n", encoding="utf-8")

            masked = update_mqtt_settings(
                config_dir,
                {
                    "enabled": True,
                    "host": "homeassistant.local",
                    "port": 1883,
                    "username": "porchlight",
                    "discovery_prefix": "homeassistant",
                    "base_topic": "porchlight",
                    "node_id": "porchlight",
                },
            )

            text = mqtt_env.read_text(encoding="utf-8")
            self.assertIn("CUSTOM_FLAG=keep", text)
            self.assertIn("MQTT_PASSWORD=old-secret", text)
            self.assertNotIn("old-secret", json.dumps(masked))
            self.assertTrue(masked["password_set"])
            self.assertEqual(oct(mqtt_env.stat().st_mode & 0o777), "0o600")

            masked = update_mqtt_settings(config_dir, {"password": ""})
            self.assertFalse(masked["password_set"])

    def test_invalid_mqtt_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                update_mqtt_settings(Path(tmp), {"host": "bad host"})
            with self.assertRaises(ValueError):
                update_mqtt_settings(Path(tmp), {"port": 70000})

    def test_openai_key_update_preserves_unknown_keys_and_masks_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            openai_env = config_dir / "porchlight.openai.env"
            openai_env.write_text("CUSTOM_FLAG=keep\nOPENAI_API_KEY=old-secret\n", encoding="utf-8")

            masked = update_openai_settings(
                config_dir,
                {
                    "api_key": "sk-test-secret",
                    "analysis_enabled": True,
                    "model": "gpt-5-mini",
                    "service_tier": "flex",
                },
            )

            text = openai_env.read_text(encoding="utf-8")
            self.assertIn("CUSTOM_FLAG=keep", text)
            self.assertIn("OPENAI_API_KEY=sk-test-secret", text)
            self.assertIn("PORCHLIGHT_AI_ANALYSIS_ENABLE=1", text)
            self.assertIn("PORCHLIGHT_AI_MODEL=gpt-5-mini", text)
            self.assertIn("PORCHLIGHT_AI_SERVICE_TIER=flex", text)
            self.assertNotIn("sk-test-secret", json.dumps(masked))
            self.assertTrue(masked["api_key_set"])
            self.assertTrue(masked["analysis_enabled"])
            self.assertEqual(masked["model"], "gpt-5-mini")
            self.assertEqual(masked["service_tier"], "flex")
            self.assertEqual(oct(openai_env.stat().st_mode & 0o777), "0o600")

            masked = update_openai_settings(config_dir, {})
            self.assertTrue(masked["api_key_set"])

            masked = update_openai_settings(config_dir, {"api_key": ""})
            self.assertFalse(masked["api_key_set"])

    def test_invalid_openai_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                update_openai_settings(Path(tmp), {"api_key": "sk bad"})
            with self.assertRaises(ValueError):
                update_openai_settings(Path(tmp), {"api_key": "sk-bad\nnext"})
            with self.assertRaises(ValueError):
                update_openai_settings(Path(tmp), {"model": "bad model"})
            with self.assertRaises(ValueError):
                update_openai_settings(Path(tmp), {"service_tier": "gold"})

    def test_openai_defaults_mask_empty_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            masked = masked_openai_settings(Path(tmp))
            self.assertFalse(masked["api_key_set"])
            self.assertFalse(masked["analysis_enabled"])
            self.assertEqual(masked["model"], "gpt-5-mini")
            self.assertEqual(masked["service_tier"], "flex")

    def test_mock_wifi_networks_feed_setup_dropdown(self):
        with mock.patch.dict("os.environ", {"PORCHLIGHT_MOCK_WIFI_SSIDS": "Kitchen WiFi,Hidden Candidate"}, clear=False):
            self.assertEqual([item["ssid"] for item in wifi_networks()], ["Kitchen WiFi", "Hidden Candidate"])

    def test_nmcli_field_parser_handles_escaped_colons(self):
        self.assertEqual(split_nmcli_fields(r"Kitchen\:IoT:82:WPA2"), ("Kitchen:IoT", "82", "WPA2"))

    def test_atomic_write_keeps_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            path.write_text("# hello\nA=1\n", encoding="utf-8")
            atomic_write_env(path, {"A": "two words", "B": "2"})
            self.assertEqual(path.read_text(encoding="utf-8"), '# hello\nA="two words"\nB=2\n')


class WebSetupApiTest(unittest.TestCase):
    def free_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def request_json(self, url, payload=None):
        if payload is None:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_setup_api_masks_mqtt_password_and_writes_request_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "var/lib/porchlight/www").mkdir(parents=True)
            (root / "var/lib/porchlight/www/index.html").write_text("ok", encoding="utf-8")
            port = self.free_port()
            env = os.environ.copy()
            env.update(
                {
                    "MUSTER_MOCK_ROOT": str(root),
                    "PORCHLIGHT_WEB_HOST": "127.0.0.1",
                    "PORCHLIGHT_WEB_PORT": str(port),
                }
            )
            process = subprocess.Popen(
                [str(ROOT / "src/porchlight-web")],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(50):
                    try:
                        self.request_json(f"{base}/api/setup/status")
                        break
                    except OSError:
                        time.sleep(0.05)
                else:
                    self.fail("web server did not start")

                saved = self.request_json(
                    f"{base}/api/setup/mqtt",
                    {
                        "enabled": True,
                        "host": "homeassistant.local",
                        "port": 1883,
                        "username": "porchlight",
                        "password": "secret",
                    },
                )

                self.assertTrue(saved["mqtt"]["enabled"])
                self.assertTrue(saved["mqtt"]["password_set"])
                self.assertNotIn("secret", json.dumps(saved))
                self.assertIn("MQTT_PASSWORD=secret", (root / "etc/porchlight/porchlight.mqtt.env").read_text())
                self.assertEqual((root / "run/porchlight/setup-action").read_text().strip(), "restart_bridge")

                saved = self.request_json(
                    f"{base}/api/setup/openai",
                    {
                        "api_key": "sk-test-secret",
                        "analysis_enabled": True,
                        "model": "gpt-5-mini",
                        "service_tier": "flex",
                    },
                )

                self.assertTrue(saved["openai"]["api_key_set"])
                self.assertTrue(saved["openai"]["analysis_enabled"])
                self.assertEqual(saved["openai"]["model"], "gpt-5-mini")
                self.assertEqual(saved["openai"]["service_tier"], "flex")
                self.assertEqual(saved["openai"]["analysis_status"]["status"], "missing")
                self.assertNotIn("sk-test-secret", json.dumps(saved))
                self.assertIn("OPENAI_API_KEY=sk-test-secret", (root / "etc/porchlight/porchlight.openai.env").read_text())

                triggered = self.request_json(f"{base}/api/setup/openai/analyze", {})
                self.assertTrue(triggered["ok"])
                self.assertEqual(triggered["message"], "AI analysis trigger accepted.")
                self.assertTrue(triggered["openai"]["api_key_set"])
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
