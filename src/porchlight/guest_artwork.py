"""Session-bound Spotify artwork from HA's fixed, authenticated media proxy."""
from __future__ import annotations

import hashlib
import json
import struct
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import __version__
from .guest_media import PLAYER
from .guest_wifi import NoRedirect

MAX_ARTWORK = 512 * 1024


def validate_artwork(body, content_type):
    """Accept bounded PNG/JPEG rasters, never markup or arbitrary upstream types."""
    if not 24 <= len(body) <= MAX_ARTWORK:
        raise ValueError("artwork_size")
    dimensions = None
    if content_type == "image/png" and body[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        dimensions = struct.unpack(">II", body[16:24])
    elif content_type == "image/jpeg" and body[:2] == b"\xff\xd8" and body[-2:] == b"\xff\xd9":
        offset = 2
        while offset + 4 <= len(body):
            if body[offset] != 255:
                break
            marker = body[offset + 1]
            if marker == 255:
                offset += 1
                continue
            size = int.from_bytes(body[offset + 2:offset + 4], "big")
            if size < 2 or offset + 2 + size > len(body):
                break
            if marker in (0xC0, 0xC1, 0xC2) and size >= 8:
                height, width = struct.unpack(">HH", body[offset + 5:offset + 9])
                dimensions = (width, height)
                break
            if marker == 0xDA:  # No frame header before the scan.
                break
            offset += 2 + size
    if dimensions is None or any(not 1 <= size <= 2048 for size in dimensions):
        raise ValueError("invalid_artwork")
    return content_type


class GuestArtwork:
    def __init__(self, settings, state, stop, opener=None):
        self.state, self.stop = state, stop
        self.base = settings.get("GUEST_HA_URL", "").rstrip("/")
        parsed = urlsplit(self.base)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path):
            raise ValueError("guest_ha_https_origin_required")
        self.token = settings.get("GUEST_HA_TOKEN", "")
        if not self.token or any(ord(c) < 33 or ord(c) > 126 for c in self.token):
            raise ValueError("guest_ha_token_required")
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.lock = threading.Lock()
        self.image = self.cached_key = self.content_type = None
        self.deadline = 0
        self.auth_failed = False

    def key(self):
        with self.state.lock:
            song = self.state.data.get("spotify") if self.state.status()["enabled"] else None
            if (song and PLAYER.fullmatch(song["id"])
                    and song["id"] in self.state.config.get("allowed_spotify_entities", [])):
                return (self.state.presentation_id, song["id"], song["title"], song["artist"], song["album"])
        return None

    @staticmethod
    def identity(key):
        return hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()[:24]

    def clear(self):
        with self.lock:
            self.image = self.cached_key = self.content_type = None
            self.deadline = 0

    def read(self, presentation_id):
        with self.state.lock:
            key = self.key()
            with self.lock:
                if (key and key[0] == presentation_id and key == self.cached_key
                        and self.state.monotonic() < self.deadline):
                    return self.image, self.content_type, self.identity(key)
        return None

    def view(self, presentation_id):
        image = self.read(presentation_id)
        return {"artwork_image": "../api/guest/spotify-art", "artwork_id": image[2]} if image else {}

    def request(self, path, limit, accept):
        request = urllib.request.Request(self.base + path, headers={
            "Authorization": "Bearer " + self.token, "Accept": accept, "User-Agent": "Porchlight/" + __version__})
        with self.opener.open(request, timeout=4) as response:
            body = response.read(limit + 1)
            content_type = response.headers.get_content_type()
        if len(body) > limit:
            raise ValueError("ha_response_size")
        return body, content_type

    def matches(self, key):
        body, content_type = self.request("/api/states/" + key[1], 32 * 1024, "application/json")
        if content_type != "application/json":
            return False
        data = json.loads(body)
        if not isinstance(data, dict) or data.get("entity_id") != key[1] or data.get("state") not in ("playing", "paused"):
            return False
        attrs = data.get("attributes", {})
        if not isinstance(attrs, dict):
            return False
        values = tuple(str(attrs[field])[:256] if attrs.get(field) else None
                       for field in ("media_title", "media_artist", "media_album_name"))
        return values == key[2:]

    def refresh(self):
        key = self.key()
        if self.auth_failed or not key:
            self.clear()
            return
        try:
            if not self.matches(key):
                raise ValueError("artwork_track_changed")
            # No URL or signed token from an entity attribute is followed or published.
            body, content_type = self.request("/api/media_player_proxy/" + key[1], MAX_ARTWORK, "image/jpeg, image/png")
            validate_artwork(body, content_type)
            if not self.matches(key):
                raise ValueError("artwork_track_changed")
            with self.state.lock:
                if self.key() != key:
                    self.clear()
                    return
                with self.lock:
                    self.image, self.content_type, self.cached_key = body, content_type, key
                    self.deadline = self.state.monotonic() + 25
        except urllib.error.HTTPError as error:
            self.auth_failed = error.code in (401, 403)
            self.clear()
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            self.clear()  # Never log HA URLs, tokens, payloads, or artwork.

    def run(self):
        previous = None
        next_refresh = 0
        while not self.stop.is_set():
            key = self.key()
            if not key:
                self.clear()
            elif key != previous or self.state.monotonic() >= next_refresh:
                self.refresh()
                next_refresh = self.state.monotonic() + 15
            previous = key
            self.stop.wait(1)
        self.clear()
