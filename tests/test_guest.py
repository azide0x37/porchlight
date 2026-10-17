import copy
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from porchlight.guest import GuestState, GuestHTTPServer, load_guest_config, wifi_payload
from porchlight.guest_mqtt import GuestMQTT, MAX_FRAME


class Clock:
    now = 1792238400.0
    tick = 100.0

    def advance(self, seconds):
        self.now += seconds
        self.tick += seconds


class GuestTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.config = json.loads((ROOT / "etc/guest.json.example").read_text())
        self.config.update(enabled=True, access_token="test-" + "x" * 40)
        self.config["wifi"] = {"ssid": "Guest", "password": "test-secret", "security": "WPA", "hidden": False}
        self.state = GuestState(self.config, lambda: self.clock.now, lambda: self.clock.tick)
        self.message = json.loads((ROOT / "examples/guest-mode/presentation.example.json").read_text())

    def send(self, **changes):
        message = copy.deepcopy(self.message)
        message["generated_at"] = datetime.fromtimestamp(self.clock.now, timezone.utc).isoformat()
        message.update(changes)
        return self.state.receive(json.dumps(message).encode())

    def heartbeat(self):
        view = self.state.view()
        return self.state.heartbeat({"session_id": view["session_id"], "presentation_id": view["presentation_id"], "visible": True})

    def test_on_requires_presenter_and_off_hides_secrets(self):
        self.assertTrue(self.send())
        self.assertEqual(self.state.status()["status"], "starting")
        self.assertEqual(self.heartbeat()["status"], "active")
        self.clock.advance(1)
        self.assertTrue(self.send(enabled=False, hvac=[]))
        self.assertEqual(self.state.view()["status"], "off")
        self.assertNotIn("wifi", self.state.view())

    def test_missing_or_expired_presenter_never_active(self):
        self.send()
        self.heartbeat()
        self.clock.advance(31)
        self.send()
        self.assertEqual(self.state.status()["status"], "degraded")
        self.assertNotIn("test-secret", json.dumps(self.state.status()))

    def test_stale_or_disconnected_state_hides_all_content(self):
        self.send()
        self.clock.advance(45)
        self.assertEqual(self.state.view()["status"], "unavailable")
        self.assertNotIn("wifi", self.state.view())
        self.send()
        self.state.disconnect()
        self.assertNotIn("hvac", self.state.view())

    def test_monotonic_expiry_survives_wall_clock_rollback(self):
        self.send()
        self.clock.now -= 100
        self.clock.tick += 46
        self.assertFalse(self.state.view()["enabled"])

    def test_old_ack_cannot_activate_new_session_or_reconnection(self):
        self.send()
        view = self.state.view()
        ack = {"session_id": view["session_id"], "presentation_id": view["presentation_id"], "visible": True}
        self.clock.advance(1)
        self.send(session_id="another-session")
        with self.assertRaises(ValueError):
            self.state.heartbeat(ack)
        view = self.state.view()
        ack.update(session_id=view["session_id"], presentation_id=view["presentation_id"])
        self.state.disconnect()
        self.clock.advance(1)
        self.send(session_id="another-session")
        with self.assertRaises(ValueError):
            self.state.heartbeat(ack)

    def test_duplicate_and_out_of_order_do_not_refresh_or_undo_off(self):
        self.send()
        timestamp = self.state.data["generated_at"]
        deadline = self.state.deadline
        self.clock.advance(10)
        self.assertFalse(self.send(generated_at=timestamp))
        self.assertEqual(deadline, self.state.deadline)
        self.send(enabled=False, hvac=[])
        self.assertFalse(self.send(generated_at=timestamp))
        self.assertEqual(self.state.status()["status"], "off")

    def test_validation_rejects_untrusted_contracts(self):
        bad = [dict(schema_version=True), dict(enabled="ON"), dict(session_id="bad/session"),
               dict(generated_at="2026-10-17T12:00:00"), dict(service="shell_command.anything"),
               dict(hvac=[{}]), dict(hvac="climate.foo"), dict(hvac=[self.message["hvac"][0]] * 9)]
        for changes in bad:
            with self.subTest(changes=changes):
                self.assertFalse(self.send(**changes))
        for seconds in (-46, 6):
            stamp = datetime.fromtimestamp(self.clock.now + seconds, timezone.utc).isoformat()
            self.assertFalse(self.send(generated_at=stamp))
        for raw in (b"{}" * 10000, b'{"a":1,"a":2}', b'[]', b'\xff', b'{"schema_version": NaN}'):
            self.assertFalse(self.state.receive(raw))

    def test_climate_is_allowlisted_numeric_and_read_only(self):
        for key, value in (("id", "climate.unapproved"), ("current_temperature", True),
                           ("target_temperature", "72"), ("target_temperature", float("inf")),
                           ("mode", "run_command"), ("unit", "K"), ("target_temperature_low", 100)):
            zone = {**self.message["hvac"][0], key: value}
            with self.subTest(key=key, value=value):
                self.assertFalse(self.send(hvac=[zone]))
        zone = {**self.message["hvac"][0], "available": False}
        self.assertTrue(self.send(hvac=[zone]))
        self.assertIsNone(self.state.view()["hvac"][0]["current_temperature"])

    def test_rejection_and_retained_packet_do_not_extend_deadline(self):
        self.send()
        deadline = self.state.deadline
        self.clock.advance(20)
        self.assertFalse(self.state.receive(json.dumps(self.message).encode(), retained=True))
        self.assertEqual(self.state.last_error, "retained_snapshot")
        self.assertEqual(deadline, self.state.deadline)

    def test_config_requires_owner_only_secret_and_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "guest.json"
            path.write_text(json.dumps(self.config))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_guest_config(path)
            path.chmod(0o600)
            self.assertEqual(load_guest_config(path), self.config)
            self.config["access_token"] = ""
            path.write_text(json.dumps(self.config))
            with self.assertRaises(ValueError):
                load_guest_config(path)

    def test_wifi_encoding_and_no_network_dependency(self):
        self.assertEqual(wifi_payload({"security": "WPA", "ssid": 'a;b,c:d"e\\f', "password": "p;ass", "hidden": True}),
                         'WIFI:T:WPA;S:a\\;b\\,c\\:d\\"e\\\\f;P:p\\;ass;H:true;;')
        self.assertEqual(wifi_payload({"security": "nopass", "ssid": "訪客", "hidden": False}),
                         "WIFI:T:nopass;S:訪客;P:;H:false;;")

    def test_mqtt_adapter_accepts_only_exact_nonretained_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = GuestMQTT(self.state, {}, Path(tmp), threading.Event())
            self.message["generated_at"] = datetime.fromtimestamp(self.clock.now, timezone.utc).isoformat()
            envelope = {"topic": adapter.topic, "retain": 0, "payload": json.dumps(self.message)}
            adapter.consume(json.dumps({**envelope, "topic": "porchlight/cmd/restart"}).encode())
            self.assertFalse(self.state.fresh())
            adapter.consume(json.dumps({**envelope, "retain": 1}).encode())
            self.assertFalse(self.state.fresh())
            adapter.consume(json.dumps({**envelope, "retain": True}).encode())
            self.assertFalse(self.state.fresh())
            adapter.consume(json.dumps({**envelope, "retain": False}).encode())
            self.assertTrue(self.state.fresh())
            adapter.consume(b"x" * (MAX_FRAME + 1))
            self.assertFalse(self.state.fresh())

    def test_mqtt_credentials_not_in_commands_or_status_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = GuestMQTT(self.state, {"MQTT_HOST": "localhost", "MQTT_USERNAME": "guest", "MQTT_PASSWORD": "private"}, Path(tmp), threading.Event())
            self.assertIn("-P private", adapter.options())
            adapter.save_status()
            self.assertNotIn("private", (Path(tmp) / "status.json").read_text())
            self.assertEqual((Path(tmp) / "status.json").stat().st_mode & 0o777, 0o600)
            adapter.settings["MQTT_PASSWORD"] = "secret\n-t #"
            with self.assertRaises(ValueError):
                adapter.options()

    def test_http_boundary_auth_no_store_and_session_ack(self):
        server = GuestHTTPServer(("127.0.0.1", 0), self.state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, body=None, token=True):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + self.config["access_token"]
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            data = json.loads(response.read())
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            connection.close()
            return response.status, data
        try:
            for path in ("/api/setup/status", "/api/setup/mqtt", "/hosts.json", "/snapshot.json", "/../etc/porchlight/guest.json", "/guest/", "/api/guest?token=anything"):
                self.assertEqual(request("GET", path)[0], 404)
            self.assertEqual(request("GET", "/api/guest", token=False)[0], 401)
            self.assertNotIn("wifi", request("GET", "/api/guest")[1])
            self.send()
            view = request("GET", "/api/guest")[1]
            ack = {"session_id": view["session_id"], "presentation_id": view["presentation_id"], "visible": True}
            self.assertEqual(request("POST", "/api/guest/heartbeat", json.dumps(ack))[1]["status"], "active")
            self.assertEqual(request("POST", "/api/guest/heartbeat", "x" * 600)[0], 400)
            self.clock.advance(46)
            self.assertNotIn("wifi", request("GET", "/api/guest")[1])
            self.assertEqual(request("POST", "/api/guest/heartbeat", json.dumps(ack))[0], 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_guest_config_survives_reinstall_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            env = {**os.environ, "MUSTER_ROOT": tmp}
            def install():
                subprocess.run([str(ROOT / "bin/install.sh")], env=env, check=True, capture_output=True)
            install()
            path = stage / "etc/porchlight/guest.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.write_text(json.dumps(self.config))
            install()
            self.assertEqual(json.loads(path.read_text()), self.config)
            subprocess.run([str(ROOT / "bin/uninstall.sh")], env=env, check=True, capture_output=True)
            self.assertTrue(path.is_file())
            subprocess.run([str(ROOT / "bin/uninstall.sh"), "--purge"], env=env, check=True, capture_output=True)
            self.assertFalse(path.exists())
