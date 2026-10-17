import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.guest import GuestState, load_guest_config, validate_presentation  # noqa: E402
from porchlight.guest_settings import masked_guest_settings, update_guest_settings  # noqa: E402
from porchlight.guest_web import (  # noqa: E402
    PREVIEW_CONFIG,
    PREVIEW_TOKEN,
    SCREEN_FILES,
    GuestScreenServer,
    screen_file,
    synthetic_presentation,
)

WEBROOT = ROOT / "src/porchlight/webroot"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ScreenAllowlistTest(unittest.TestCase):
    def test_only_screen_assets_are_reachable(self):
        for path, relative in SCREEN_FILES.items():
            self.assertEqual(screen_file(path), relative)
            self.assertTrue((WEBROOT / relative).is_file(), relative)
        self.assertEqual(screen_file("/fonts/inter-latin.woff2"), "fonts/inter-latin.woff2")
        for denied in [
            "/index.html",
            "/app.js",
            "/style.css",
            "/hosts.json",
            "/snapshot.json",
            "/api/setup/status",
            "/fonts/inter-greek.woff2",
            "/fonts/../index.html",
            "/guest/../index.html",
            "/guest/guest.css/",
            "/manifest.webmanifest",
        ]:
            self.assertIsNone(screen_file(denied), denied)

    def test_screen_assets_declare_transitions_and_contract(self):
        index = (WEBROOT / "guest/index.html").read_text(encoding="utf-8")
        css = (WEBROOT / "guest/guest.css").read_text(encoding="utf-8")
        js = (WEBROOT / "guest/guest.js").read_text(encoding="utf-8")
        vendor = (WEBROOT / "guest/vendor/qrcode-generator.js").read_text(encoding="utf-8")
        self.assertIn("Porchlight - Hosting Guests", index)
        self.assertIn("/guest/guest.css?v=2.4.0", index)
        self.assertIn("/guest/guest.js?v=2.4.0", index)
        self.assertIn("/guest/vendor/qrcode-generator.js?v=2.4.0", index)
        self.assertIn("/guest/arrive.js?v=2.4.0", index)
        self.assertIn("pagereveal", (WEBROOT / "guest/arrive.js").read_text(encoding="utf-8"))
        self.assertNotIn("<style", index)
        self.assertNotIn("onload=", index)
        self.assertIn("@view-transition", css)
        self.assertIn("navigation: auto", css)
        self.assertIn("view-transition-name: porch-lamp", css)
        self.assertIn("view-transition-name: clock", css)
        self.assertIn("view-transition-name: spotlight", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("--u: min(1vh, 0.5625vw)", css)
        self.assertIn("startViewTransition", js)
        self.assertIn('"/api/guest"', js)
        self.assertIn('"/api/guest/heartbeat"', js)
        self.assertIn("presentation_id", js)
        self.assertIn("sessionStorage", js)
        self.assertIn("STALE_MS = 45000", js)
        self.assertIn('stringToBytesFuncs["UTF-8"]', js)
        self.assertIn("Kazuhiko Arase", vendor)
        self.assertIn("MIT", vendor)
        self.assertIn("stringToBytesFuncs['UTF-8']", vendor)

    def test_vendored_qr_library_encodes_wifi_payload(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        script = """
          const fs = require('fs');
          const vm = require('vm');
          const context = { window: {} };
          vm.createContext(context);
          vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + '\\nwindow.qrcode = qrcode;', context);
          const qrcode = context.window.qrcode;
          qrcode.stringToBytes = qrcode.stringToBytesFuncs['UTF-8'];
          const code = qrcode(0, 'M');
          code.addData(process.argv[2], 'Byte');
          code.make();
          const n = code.getModuleCount();
          const finder = (r, c) => [0, 1, 2, 3, 4, 5, 6].every((i) => code.isDark(r + i, c) && code.isDark(r, c + i));
          console.log(JSON.stringify({ n, finders: finder(0, 0) && finder(0, n - 7) && finder(n - 7, 0) }));
        """
        payload = "WIFI:T:WPA;S:Caf\u00e9 \\;Guest;P:p\u00e4ss\\:word;H:false;;"
        result = subprocess.run(
            [node, "-e", script, str(WEBROOT / "guest/vendor/qrcode-generator.js"), payload],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertGreaterEqual(data["n"], 29)
        self.assertTrue(data["finders"])


class PreviewFeedContractTest(unittest.TestCase):
    def test_synthetic_presentation_matches_receiver_schema(self):
        allowed = set(PREVIEW_CONFIG["allowed_climate_entities"])
        for enabled in (True, False):
            data, _ = validate_presentation(synthetic_presentation(enabled, "preview-1", 3), allowed, time.time())
            self.assertEqual(data["enabled"], enabled)
            self.assertEqual(len(data["hvac"]), 2 if enabled else 0)


class GuestScreenServerTest(unittest.TestCase):
    def setUp(self):
        self.state = GuestState(json.loads(json.dumps(PREVIEW_CONFIG)))
        self.port = free_port()
        self.server = GuestScreenServer(("127.0.0.1", self.port), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path, token=None):
        request = urllib.request.Request(self.base + path)
        if token:
            request.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def post(self, path, payload, token):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_screen_is_served_with_kiosk_headers_and_admin_paths_stay_closed(self):
        status, headers, body = self.get("/guest/")
        self.assertEqual(status, 200)
        self.assertIn("Porchlight - Hosting Guests", body.decode("utf-8"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        status, headers, _ = self.get("/fonts/fraunces-latin.woff2")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "font/woff2")
        self.assertIn("max-age", headers["Cache-Control"])
        status, _, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ui_available"])
        for denied in ["/index.html", "/hosts.json", "/snapshot.json", "/api/setup/status", "/app.js", "/fonts/inter-greek.woff2"]:
            status, _, _ = self.get(denied)
            self.assertEqual(status, 404, denied)

    def test_bare_guest_path_redirects_without_touching_the_fragment(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("GET", "/guest")
            response = connection.getresponse()
            self.assertEqual(response.status, 308)
            self.assertEqual(response.getheader("Location"), "/guest/")
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
        finally:
            connection.close()

    def test_view_requires_token_and_heartbeat_marks_presenter_active(self):
        status, _, _ = self.get("/api/guest")
        self.assertEqual(status, 401)
        status, _, body = self.get("/api/guest", PREVIEW_TOKEN)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["enabled"])

        self.assertTrue(self.state.receive(synthetic_presentation(True, "session-1", 0)))
        status, headers, body = self.get("/api/guest", PREVIEW_TOKEN)
        view = json.loads(body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(view["enabled"])
        self.assertEqual(view["status"], "starting")
        self.assertEqual(view["wifi"]["qr_payload"], "WIFI:T:WPA;S:Porchlight Guest;P:lantern-on-the-porch;H:false;;")
        self.assertEqual(len(view["hvac"]), 2)

        status, ack = self.post(
            "/api/guest/heartbeat",
            {"session_id": view["session_id"], "presentation_id": view["presentation_id"], "visible": True},
            PREVIEW_TOKEN,
        )
        self.assertEqual(status, 200)
        self.assertEqual(ack["status"], "active")

        status, rejected = self.post(
            "/api/guest/heartbeat",
            {"session_id": view["session_id"], "presentation_id": "stale-presentation", "visible": True},
            PREVIEW_TOKEN,
        )
        self.assertEqual(status, 400)
        self.assertIn("error", rejected)

    def test_off_presentation_hides_credentials(self):
        self.assertTrue(self.state.receive(synthetic_presentation(False, "session-off", 0)))
        _, _, body = self.get("/api/guest", PREVIEW_TOKEN)
        view = json.loads(body)
        self.assertFalse(view["enabled"])
        self.assertEqual(view["status"], "off")
        self.assertNotIn("wifi", view)
        self.assertNotIn("lantern-on-the-porch", body.decode("utf-8"))



class GuestSettingsTest(unittest.TestCase):
    def test_dashboard_writes_owner_only_config_the_backend_accepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "etc/porchlight"
            masked = update_guest_settings(
                config_dir,
                {
                    "enabled": True,
                    "welcome": "Welcome, friends",
                    "title": "House notes",
                    "ssid": "Porch Guest",
                    "security": "WPA",
                    "password": "lantern-on-the-porch",
                    "hidden": False,
                    "alexa": {"lights": "Alexa, lights on.\nAlexa, lights off.", "music": [], "blinds": ["Alexa, close blind 50%."]},
                    "allowed_climate_entities": "climate.guest_room, climate.living_room",
                },
            )
            path = config_dir / "guest.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            data = load_guest_config(path)
            self.assertTrue(data["enabled"])
            self.assertEqual(data["wifi"]["password"], "lantern-on-the-porch")
            self.assertEqual(data["alexa"], {"lights": ["Alexa, lights on.", "Alexa, lights off."], "blinds": ["Alexa, close blind 50%."]})
            self.assertEqual(data["allowed_climate_entities"], ["climate.guest_room", "climate.living_room"])
            self.assertTrue(masked["wifi"]["password_set"])
            self.assertNotIn("lantern-on-the-porch", json.dumps({k: v for k, v in masked.items() if k != "access_token_once"}))
            self.assertRegex(masked["access_token_once"], r"^[A-Za-z0-9_-]{32,128}$")
            self.assertEqual(masked["access_token_once"], data["access_token"])

            # Blank password keeps the stored one; blank SSID removes Wi-Fi entirely.
            again = update_guest_settings(config_dir, {"ssid": "Porch Guest", "password": "", "security": "WPA"})
            self.assertNotIn("access_token_once", again)
            self.assertEqual(load_guest_config(path)["wifi"]["password"], "lantern-on-the-porch")
            update_guest_settings(config_dir, {"ssid": ""})
            self.assertIsNone(load_guest_config(path)["wifi"])
            self.assertFalse(masked_guest_settings(config_dir)["wifi"]["password_set"])

            # Open networks drop the password; rotation issues a different token.
            update_guest_settings(config_dir, {"ssid": "Open Porch", "security": "nopass"})
            self.assertEqual(load_guest_config(path)["wifi"]["password"], "")
            rotated = update_guest_settings(config_dir, {"rotate_token": True})
            self.assertNotEqual(rotated["access_token_once"], masked["access_token_once"])

    def test_dashboard_rejects_what_the_backend_would_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "etc/porchlight"
            with self.assertRaises(ValueError):
                update_guest_settings(config_dir, {"enabled": True, "ssid": "Porch", "password": "short"})
            with self.assertRaises(ValueError):
                update_guest_settings(config_dir, {"alexa": {"lights": ["a", "b", "c", "d"]}})
            with self.assertRaises(ValueError):
                update_guest_settings(config_dir, {"allowed_climate_entities": "light.not_climate"})
            with self.assertRaises(ValueError):
                update_guest_settings(config_dir, {"welcome": "bad\x01control"})
            self.assertFalse((config_dir / "guest.json").exists())


class AdminListenerTest(unittest.TestCase):
    def request(self, url, payload=None):
        if payload is None:
            request = urllib.request.Request(url)
        else:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_admin_listener_never_serves_guest_surface_and_saves_guest_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            www = root / "var/lib/porchlight/www"
            (www / "guest").mkdir(parents=True)
            (www / "index.html").write_text("ok", encoding="utf-8")
            (www / "guest/index.html").write_text("should never be served here", encoding="utf-8")
            port = free_port()
            env = os.environ.copy()
            env.update({"MUSTER_MOCK_ROOT": str(root), "PORCHLIGHT_WEB_HOST": "127.0.0.1", "PORCHLIGHT_WEB_PORT": str(port)})
            process = subprocess.Popen([str(ROOT / "src/porchlight-web")], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(50):
                    try:
                        status, _ = self.request(f"{base}/api/setup/status")
                    except OSError:
                        status = None
                    if status == 200:
                        break
                    time.sleep(0.05)
                else:
                    self.fail("web server did not start")
                for path in ("/guest", "/guest/", "/guest/index.html", "/api/guest", "/api/guest/heartbeat"):
                    status, _ = self.request(base + path)
                    self.assertEqual(status, 404, path)
                status, body = self.request(f"{base}/api/setup/status")
                guest = json.loads(body)["guest"]
                self.assertFalse(guest["configured"])
                self.assertEqual(guest["receiver"]["status"], "stopped")

                status, body = self.request(
                    f"{base}/api/setup/guest",
                    {"enabled": True, "ssid": "Porch Guest", "password": "lantern-on-the-porch", "security": "WPA", "allowed_climate_entities": ["climate.guest_room"]},
                )
                self.assertEqual(status, 200, body)
                saved = json.loads(body)["guest"]
                self.assertTrue(saved["configured"])
                self.assertTrue(saved["wifi"]["password_set"])
                self.assertNotIn("lantern-on-the-porch", body.decode("utf-8"))
                self.assertIn("access_token_once", saved)
                config_path = root / "etc/porchlight/guest.json"
                self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(load_guest_config(config_path)["wifi"]["ssid"], "Porch Guest")
                self.assertEqual((root / "run/porchlight/setup-action").read_text().strip(), "restart_guest")

                status, body = self.request(f"{base}/api/setup/guest", {"password": "short"})
                self.assertEqual(status, 400)
                self.assertIn("8-63", json.loads(body)["error"])
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
