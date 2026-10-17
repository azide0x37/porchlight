"""Read one configured HA Wi-Fi image. Credentials and QR pixels stay off MQTT."""
from __future__ import annotations

import re
import struct
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit

MAX_IMAGE = 128 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("ha_redirect_refused")


class GuestWifi:
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
        self.entity = settings.get("GUEST_WIFI_QR_ENTITY", "")
        if not re.fullmatch(r"image\.[a-z0-9_]{1,100}", self.entity):
            raise ValueError("guest_wifi_image_required")
        self.ssid = settings.get("GUEST_WIFI_SSID", "")
        if not self.ssid or len(self.ssid.encode()) > 32 or any(ord(c) < 32 for c in self.ssid):
            raise ValueError("guest_wifi_ssid_required")
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.lock = threading.Lock()
        self.image = None
        self.presentation_id = None
        self.deadline = 0
        self.auth_failed = False

    def clear(self):
        with self.lock:
            self.image = self.presentation_id = None
            self.deadline = 0

    def read(self, presentation_id):
        with self.lock:
            if self.presentation_id == presentation_id and self.state.monotonic() < self.deadline:
                return self.image
        return None

    def view(self, presentation_id):
        if self.read(presentation_id):
            return {"ssid": self.ssid, "security": "WPA", "hidden": False, "qr_image": "../api/guest/wifi-qr"}
        return None

    def refresh(self):
        if self.auth_failed:
            self.clear()
            return
        with self.state.lock:
            if not self.state.status()["enabled"]:
                self.clear()
                return
            presentation_id = self.state.presentation_id
        try:
            request = urllib.request.Request(self.base + "/api/image_proxy/" + self.entity,
                                             headers={"Authorization": "Bearer " + self.token, "Accept": "image/png"})
            with self.opener.open(request, timeout=4) as response:
                body = response.read(MAX_IMAGE + 1)
                if response.headers.get_content_type() != "image/png":
                    raise ValueError("unexpected_image_type")
            # UniFi QR images are PNG. Refuse HTML/SVG, huge files and oversized canvases.
            if (not 24 <= len(body) <= MAX_IMAGE or body[:8] != b"\x89PNG\r\n\x1a\n"
                    or body[12:16] != b"IHDR" or any(not 1 <= size <= 2048 for size in struct.unpack(">II", body[16:24]))):
                raise ValueError("invalid_wifi_image")
            with self.state.lock:
                if not self.state.status()["enabled"] or self.state.presentation_id != presentation_id:
                    self.clear()
                    return
                with self.lock:
                    self.image, self.presentation_id = body, presentation_id
                    self.deadline = self.state.monotonic() + 25
        except urllib.error.HTTPError as error:
            self.auth_failed = error.code in (401, 403)
            self.clear()  # Stop retrying bad credentials until the service restarts.
        except (OSError, ValueError):
            self.clear()  # No exception text: it can contain URLs or credentials.

    def run(self):
        next_refresh = 0
        while not self.stop.is_set():
            if not self.state.status()["enabled"]:
                self.clear()
                next_refresh = 0
            elif time.monotonic() >= next_refresh:
                self.refresh()
                next_refresh = time.monotonic() + 15
            self.stop.wait(1)
        self.clear()
