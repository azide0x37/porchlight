import copy
import io
import json
import struct
import sys
import threading
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from porchlight.guest import GuestState
from porchlight.guest_media import validate_jam
from porchlight.guest_wifi import GuestWifi, NoRedirect
from porchlight.guest_web import PREVIEW_CONFIG, synthetic_presentation
from porchlight.guest_settings import bind_jam_invite, update_guest_ha_settings
from porchlight.config import load_env_file

PLAYER = "media_player.spotify_test"
SONG = {"id": PLAYER, "state": "playing", "title": "A song", "artist": "An artist",
        "album": None, "source": "Living room", "duration": 180, "position": 15}


class GuestMediaTest(unittest.TestCase):
    def setUp(self):
        self.now, self.tick = 1792238400., 100.
        self.config = copy.deepcopy(PREVIEW_CONFIG)
        self.config["allowed_spotify_entities"] = [PLAYER]
        self.config["spotify_jam"] = {"url": "https://spotify.link/testInvite", "session_id": "test",
                                      "expires_at": self.stamp(self.now + 60)}
        self.state = GuestState(self.config, lambda: self.now, lambda: self.tick)

    @staticmethod
    def stamp(value):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    def send(self, song=SONG, **changes):
        data = json.loads(synthetic_presentation(True, "test", 0))
        data.update(generated_at=self.stamp(self.now), spotify=song, **changes)
        return self.state.receive(json.dumps(data).encode())

    def test_media_requires_allowlist_and_bounded_fields(self):
        for song in [{**SONG, "id": "media_player.other"}, {**SONG, "title": "x" * 257},
                     {**SONG, "position": 10 ** 500}, {**SONG, "duration": True},
                     {**SONG, "entity_picture": "/api/media_player_proxy?token=secret"}]:
            with self.subTest(song=song):
                self.assertFalse(self.send(song))
        self.assertTrue(self.send())
        self.assertEqual(self.state.view()["spotify"]["title"], "A song")
        self.assertNotIn("spotify", self.state.status())

    def test_jam_is_explicit_session_bound_and_expires(self):
        self.send()
        self.assertEqual(self.state.view()["spotify"]["jam"]["url"], self.config["spotify_jam"]["url"])
        self.now += 1
        self.send(session_id="next-visit")
        self.assertIsNone(self.state.view()["spotify"]["jam"])
        self.now += 60
        self.tick += 61
        self.send()
        self.assertIsNone(self.state.view()["spotify"]["jam"])
        # A wall-clock rollback cannot resurrect the invitation.
        self.now -= 30
        self.state.timestamp = float("-inf")
        self.send()
        self.assertIsNone(self.state.view()["spotify"]["jam"])

    def test_idle_off_and_stale_never_offer_a_jam(self):
        self.send(None)
        self.assertIsNone(self.state.view()["spotify"])
        self.now += 1
        self.send()
        self.state.disconnect()
        self.assertNotIn("spotify", self.state.view())
        self.now += 1
        self.assertFalse(self.send(enabled=False, hvac=[]))
        self.assertTrue(self.send(None, enabled=False, hvac=[]))
        self.assertNotIn("spotify", self.state.view())

    def test_jam_rejects_other_urls_and_track_links(self):
        for url in ("http://spotify.link/testInvite", "https://evil.test/testInvite",
                    "https://open.spotify.com/track/123456", "https://spotify.link.evil.test/testInvite",
                    "https://spotify.link/testInvite?token=other", "https://user@spotify.link/testInvite"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_jam({**self.config["spotify_jam"], "url": url})

    def test_host_invite_requires_a_fresh_active_session(self):
        self.send()
        payload = {"spotify_jam_url": "https://spotify.link/testInvite"}
        bound = bind_jam_invite(payload, self.state.status(), self.now)
        self.assertEqual(bound["spotify_jam"]["session_id"], "test")
        with self.assertRaises(ValueError):
            bind_jam_invite(payload, self.state.status(), self.now + 46)
        self.assertIsNone(bind_jam_invite({"spotify_jam_url": ""}, {}, self.now)["spotify_jam"])


class ImageResponse(io.BytesIO):
    def __init__(self, body, content_type="image/png"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class GuestWifiTest(unittest.TestCase):
    def setUp(self):
        self.state = GuestState(copy.deepcopy(PREVIEW_CONFIG))
        self.state.receive(synthetic_presentation(True, "wifi-test", 0))
        self.settings = {"GUEST_HA_URL": "https://ha.example.test", "GUEST_HA_TOKEN": "private-test-token",
                         "GUEST_WIFI_QR_ENTITY": "image.botanical_qr_code", "GUEST_WIFI_SSID": "Botanical"}
        self.body = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 148, 148)
        outer = self
        class Opener:
            def open(self, request, timeout):
                outer.request, outer.timeout = request, timeout
                if outer.during_read:
                    outer.during_read()
                return ImageResponse(outer.body)
        self.during_read = None
        self.provider = GuestWifi(self.settings, self.state, threading.Event(), Opener())
        self.state.wifi_provider = self.provider

    def test_proxy_uses_fixed_entity_bearer_and_private_memory(self):
        self.provider.refresh()
        self.assertEqual(self.request.full_url, "https://ha.example.test/api/image_proxy/image.botanical_qr_code")
        self.assertEqual(self.request.get_header("Authorization"), "Bearer private-test-token")
        self.assertTrue(self.request.get_header("User-agent").startswith("Porchlight/"))
        self.assertEqual(self.state.view()["wifi"], {"ssid": "Botanical", "security": "WPA", "hidden": False,
                                                     "qr_image": "../api/guest/wifi-qr"})
        self.assertNotIn("private-test-token", json.dumps(self.state.view()))
        self.state.disconnect()
        self.provider.refresh()
        self.assertIsNone(self.provider.read(self.state.presentation_id))

    def test_late_response_cannot_populate_another_or_off_session(self):
        self.during_read = self.state.disconnect
        self.provider.refresh()
        self.assertIsNone(self.provider.read(self.state.presentation_id))

    def test_bad_image_clears_previous_pixels(self):
        self.provider.refresh()
        self.body = b"<svg>private</svg>"
        self.provider.refresh()
        self.assertIsNone(self.provider.read(self.state.presentation_id))

    def test_https_and_redirects_are_required(self):
        for origin in ("http://ha.test", "https://ha.test/api", "https://user:secret@ha.test"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                GuestWifi({**self.settings, "GUEST_HA_URL": origin}, self.state, threading.Event())
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test")

    def test_owner_settings_never_echo_token_and_clear_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "guest.env").write_text("GUEST_WEB_PORT=12345\n")
            result = update_guest_ha_settings(root, {"url": "https://ha.example.test", "token": "secret-value",
                                                    "wifi_qr_entity": "image.botanical_qr_code", "wifi_ssid": "Botanical"})
            self.assertNotIn("secret-value", json.dumps(result))
            self.assertTrue(result["ha"]["token_set"])
            self.assertEqual((root / "guest.env").stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_env_file(root / "guest.env")["GUEST_WEB_PORT"], "12345")
            update_guest_ha_settings(root, {"clear_token": True})
            self.assertEqual(load_env_file(root / "guest.env")["GUEST_HA_TOKEN"], "")
