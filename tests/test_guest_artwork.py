import copy
import http.client
import io
import json
import struct
import sys
import threading
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from porchlight.guest import GuestHTTPServer, GuestState
from porchlight.guest_artwork import GuestArtwork, MAX_ARTWORK, validate_artwork
from porchlight.guest_web import PREVIEW_CONFIG, synthetic_presentation

PLAYER = "media_player.spotify_preview"
SONG = {"id": PLAYER, "state": "playing", "title": "Test song", "artist": "Test artist",
        "album": "Test album", "source": None, "duration": 180, "position": 15}
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 300, 300)
JPEG = b"\xff\xd8\xff\xe0\x00\x04ab\xff\xc0\x00\x11\x08" + struct.pack(">HH", 300, 300) + b"\x03" + b"\x00" * 9 + b"\xff\xd9"


class Response(io.BytesIO):
    def __init__(self, body, content_type):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class GuestArtworkTest(unittest.TestCase):
    def setUp(self):
        self.now, self.tick = 1792238400., 100.
        self.state = GuestState(copy.deepcopy(PREVIEW_CONFIG), lambda: self.now, lambda: self.tick)
        self.settings = {"GUEST_HA_URL": "https://ha.example.test", "GUEST_HA_TOKEN": "private-test-token"}
        self.metadata = {"entity_id": PLAYER, "state": "playing", "attributes": {
            "media_title": SONG["title"], "media_artist": SONG["artist"], "media_album_name": SONG["album"],
            "entity_picture": "https://untrusted.test/image?token=private-signed-token"}}
        self.body, self.content_type = JPEG, "image/jpeg"
        self.requests = []
        self.during_image = None
        self.error = None
        outer = self
        class Opener:
            def open(self, request, timeout):
                outer.requests.append(request)
                if outer.error:
                    raise outer.error
                if "/api/states/" in request.full_url:
                    return Response(json.dumps(outer.metadata).encode(), "application/json")
                if outer.during_image:
                    outer.during_image()
                return Response(outer.body, outer.content_type)
        self.provider = GuestArtwork(self.settings, self.state, threading.Event(), Opener())
        self.state.artwork_provider = self.provider
        self.send()

    def send(self, song=SONG, **changes):
        self.now += 1
        data = json.loads(synthetic_presentation(True, "artwork-test", 0))
        data.update(generated_at=datetime.fromtimestamp(self.now, timezone.utc).isoformat(), spotify=song, **changes)
        self.assertTrue(self.state.receive(json.dumps(data).encode()), self.state.last_error)

    def test_fixed_proxy_and_credentials_stay_on_server(self):
        self.provider.refresh()
        self.assertEqual([r.full_url for r in self.requests], [
            "https://ha.example.test/api/states/" + PLAYER,
            "https://ha.example.test/api/media_player_proxy/" + PLAYER,
            "https://ha.example.test/api/states/" + PLAYER])
        self.assertTrue(all(r.get_header("Authorization") == "Bearer private-test-token" for r in self.requests))
        self.assertTrue(all(r.get_header("User-agent").startswith("Porchlight/") for r in self.requests))
        song = self.state.view()["spotify"]
        self.assertEqual(song["artwork_image"], "../api/guest/spotify-art")
        self.assertRegex(song["artwork_id"], r"^[0-9a-f]{24}$")
        self.assertNotIn("private-", json.dumps(self.state.view()))
        self.assertNotIn("artwork_image", json.dumps(self.state.status()))

    def test_track_change_immediately_hides_old_artwork(self):
        self.provider.refresh()
        old_id = self.state.view()["spotify"]["artwork_id"]
        self.send({**SONG, "title": "Next track"})
        self.assertIsNone(self.provider.read(self.state.presentation_id))
        self.provider.refresh()  # HA and MQTT disagree; do not attach the wrong cover.
        self.assertNotIn("artwork_image", self.state.view()["spotify"])
        self.metadata["attributes"]["media_title"] = "Next track"
        self.provider.refresh()
        self.assertNotEqual(self.state.view()["spotify"]["artwork_id"], old_id)

    def test_late_or_cross_session_image_is_discarded(self):
        for during_read in (lambda: self.state.disconnect(), lambda: self.send(session_id="next-session"),
                            lambda: self.metadata["attributes"].update(media_title="Another track")):
            self.setUp()
            self.during_image = during_read
            self.provider.refresh()
            self.assertIsNone(self.provider.read(self.state.presentation_id))

    def test_off_idle_expiry_and_wrong_presentation_hide_artwork(self):
        self.provider.refresh()
        self.assertIsNone(self.provider.read("wrong-presentation"))
        self.tick += 25
        self.assertIsNone(self.provider.read(self.state.presentation_id))
        self.provider.refresh()
        self.send(None)
        self.assertIsNone(self.provider.read(self.state.presentation_id))
        self.send()
        self.provider.refresh()
        self.send(None, enabled=False, hvac=[])
        self.assertIsNone(self.provider.read(self.state.presentation_id))
        self.send()
        self.provider.refresh()
        self.tick += 45
        self.assertIsNone(self.provider.read(self.state.presentation_id))

    def test_raster_types_dimensions_and_body_are_bounded(self):
        self.assertEqual(validate_artwork(PNG, "image/png"), "image/png")
        self.assertEqual(validate_artwork(JPEG, "image/jpeg"), "image/jpeg")
        bad = [(b"<svg>not raster</svg>" * 2, "image/svg+xml"), (JPEG, "text/html"),
               (JPEG[:-2], "image/jpeg"), (b"x" * (MAX_ARTWORK + 1), "image/jpeg"),
               (PNG[:16] + struct.pack(">II", 9999, 300), "image/png"),
               (b"\xff\xd8\xff\xe0\xff\xff" + b"x" * 24 + b"\xff\xd9", "image/jpeg")]
        for body, content_type in bad:
            with self.subTest(content_type=content_type), self.assertRaises(ValueError):
                validate_artwork(body, content_type)

    def test_failure_clears_cover_and_auth_failure_stops_retries(self):
        self.provider.refresh()
        self.body = b"bad response"
        self.provider.refresh()
        self.assertIsNone(self.provider.read(self.state.presentation_id))
        self.error = urllib.error.HTTPError("https://ha.example.test", 401, "Unauthorized", {}, None)
        self.provider.refresh()
        count = len(self.requests)
        self.provider.refresh()
        self.assertEqual(len(self.requests), count)

    def test_http_auth_no_store_track_and_session_headers(self):
        self.provider.refresh()
        server = GuestHTTPServer(("127.0.0.1", 0), self.state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def get(token=True):
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            connection.request("GET", "/api/guest/spotify-art", headers={
                "Authorization": "Bearer " + self.state.config["access_token"]} if token else {})
            response = connection.getresponse()
            body = response.read()
            connection.close()
            return response, body
        try:
            self.assertEqual(get(False)[0].status, 401)
            response, body = get()
            self.assertEqual((response.status, body), (200, JPEG))
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertEqual(response.getheader("Content-Type"), "image/jpeg")
            self.assertEqual(response.getheader("X-Porchlight-Presentation"), self.state.presentation_id)
            self.assertEqual(response.getheader("X-Porchlight-Artwork"), self.state.view()["spotify"]["artwork_id"])
            self.send(None, enabled=False, hvac=[])
            self.assertEqual(get()[0].status, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
