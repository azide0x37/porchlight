"""Guest TV screen: the allowlisted static presentation surface for the restricted guest backend.

The screen is served by the guest backend process (``porchlight-guest``), never by the
administrative dashboard listener. Only the files named here are reachable; the JSON view,
token check, heartbeat, and presentation validation live in :mod:`porchlight.guest`.

``python -m porchlight.guest_web --preview`` runs the same handler against a synthetic,
in-memory presentation feed so the screen can be designed, demonstrated, and tested
without Home Assistant, MQTT, or any real guest credentials.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import signal
import threading
import time
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from .guest import FRESH_SECONDS, GuestHandler, GuestHTTPServer, GuestState

WEBROOT = Path(__file__).resolve().parent / "webroot"
SCREEN_PATH = "/guest/"
TEXT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
BINARY_TYPES = {".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2"}
SCREEN_FILES = {
    "/guest/": "guest/index.html",
    "/guest/index.html": "guest/index.html",
    "/guest/guest.css": "guest/guest.css",
    "/guest/guest.js": "guest/guest.js",
    "/guest/arrive.js": "guest/arrive.js",
    "/guest/vendor/qrcode-generator.js": "guest/vendor/qrcode-generator.js",
    "/icon-round.png": "icon-round.png",
    "/icon.svg": "icon.svg",
}
SCREEN_FONTS = frozenset(
    {
        "inter-latin.woff2",
        "inter-latin-ext.woff2",
        "fraunces-latin.woff2",
        "fraunces-latin-ext.woff2",
        "jetbrains-latin.woff2",
        "jetbrains-latin-ext.woff2",
    }
)
# The page carries no inline scripts or styles; the QR code is built into inline SVG by the
# bundled library, and all data comes from the same-origin guest API.
SCREEN_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' blob:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'"
)
STATIC_CACHE = "public, max-age=604800"


def screen_file(path: str) -> str | None:
    """Map an allowlisted request path to a webroot-relative file, or ``None``."""
    if path in SCREEN_FILES:
        return SCREEN_FILES[path]
    if path.startswith("/fonts/"):
        name = path[len("/fonts/"):]
        if name in SCREEN_FONTS:
            return "fonts/" + name
    return None


class GuestScreenHandler(GuestHandler):
    """The JSON-only guest handler plus the allowlisted static screen."""

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/healthz":
            self.reply(200, {"service": "porchlight-guest", "ui_available": True, "screen": SCREEN_PATH})
            return
        if path == "/guest":
            self.redirect(SCREEN_PATH)
            return
        relative = screen_file(path)
        if relative is None:
            super().do_GET()
            return
        self.send_file(relative)

    def redirect(self, location: str) -> None:
        self.send_response(308)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def send_file(self, relative: str) -> None:
        target = WEBROOT / relative
        try:
            body = target.read_bytes()
        except OSError:
            self.reply(404, {"error": "not_found"})
            return
        suffix = target.suffix
        content_type = TEXT_TYPES.get(suffix) or BINARY_TYPES.get(suffix) or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if suffix in TEXT_TYPES else STATIC_CACHE)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if suffix == ".html":
            self.send_header("Content-Security-Policy", SCREEN_CSP)
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


class GuestScreenServer(GuestHTTPServer):
    """``GuestHTTPServer`` that serves the TV screen alongside the guest API."""

    def __init__(self, address, state: GuestState):
        self.state = state
        ThreadingHTTPServer.__init__(self, address, GuestScreenHandler)


# --------------------------------------------------------------------------------------
# Synthetic preview. Nothing below is used by the appliance service.
# --------------------------------------------------------------------------------------

PREVIEW_TOKEN = "preview-token-not-a-secret-0000000000"
PREVIEW_SCENARIOS = ("active", "off", "stale", "cycle")
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "examples" / "guest-mode" / "fixtures"
FIXTURE_NAME = re.compile(r"^[a-z_]{1,40}$")
PREVIEW_CONFIG = {
    "schema_version": 1,
    "enabled": True,
    "allowed_spotify_entities": ["media_player.spotify_preview"],
    "welcome": "Welcome — make yourself at home",
    "home_name": "Botanical",
    "wifi": {"ssid": "Porchlight Guest", "security": "WPA", "password": "lantern-on-the-porch", "hidden": False},
    "alexa": {
        "lights": ["Alexa, turn all lights to sunset.", "Alexa, turn kitchen lights to white."],
        "music": ["Alexa, play jazz in the living room.", "Alexa, stop music in the living room."],
        "blinds": ["Alexa, close blind 50%."],
    },
    "presentation": {
        "title": "A few things for your stay",
        "stale_after_seconds": FRESH_SECONDS,
        "exit_policy": "neutral_screen_keep_tv_on",
    },
    "access_token": PREVIEW_TOKEN,
    # The synthetic zones plus the three zones the household's Home Assistant package emits,
    # so the committed fixtures under examples/guest-mode/fixtures replay unchanged.
    "allowed_climate_entities": [
        "climate.guest_room",
        "climate.living_room",
        "climate.living_room_thermostat",
        "climate.bedroom_ac",
        "climate.kitchen_ac",
    ],
}


def fixture_path(name: str) -> Path:
    if not FIXTURE_NAME.fullmatch(name):
        raise ValueError("unknown fixture")
    path = FIXTURE_DIR / f"presentation.{name}.json"
    if not path.is_file():
        raise ValueError("unknown fixture")
    return path


def fixture_names() -> list[str]:
    if not FIXTURE_DIR.is_dir():
        return []
    return sorted(p.name[len("presentation."):-len(".json")] for p in FIXTURE_DIR.glob("presentation.*.json"))


def fixture_presentation(path: Path, session_id: str) -> bytes:
    """Replay a committed fixture as a live snapshot: fresh timestamp and session, same zones."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    data["session_id"] = session_id
    return json.dumps(data).encode("utf-8")


def synthetic_presentation(enabled: bool, session_id: str, tick: int) -> bytes:
    """A presentation payload shaped exactly like the Home Assistant starter publishes."""
    drift = ((tick % 8) - 4) * 0.25
    zones = [
        {
            "id": "climate.guest_room",
            "label": "Guest room",
            "available": True,
            "unit": "°F",
            "mode": "heat_cool",
            "action": "idle",
            "current_temperature": round(71 + drift, 1),
            "target_temperature": None,
            "target_temperature_low": 68,
            "target_temperature_high": 74,
        },
        {
            "id": "climate.living_room",
            "label": "Living room",
            "available": True,
            "unit": "°F",
            "mode": "heat",
            "action": "heating" if tick % 6 < 3 else "idle",
            "current_temperature": round(69 + drift / 2, 1),
            "target_temperature": 70,
            "target_temperature_low": None,
            "target_temperature_high": None,
        },
    ]
    payload = {
        "schema_version": 1,
        "enabled": enabled,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "hvac": zones if enabled else [],
    }
    if enabled:
        payload["spotify"] = {
            "id": "media_player.spotify_preview", "state": "playing", "title": "A little music for your stay",
            "artist": "Porchlight preview", "album": None, "source": "Living room",
            "duration": 240, "position": 30,
        }
    return json.dumps(payload).encode("utf-8")


class PreviewFeeder(threading.Thread):
    """Feeds synthetic presentations into a ``GuestState`` on a 10-second heartbeat."""

    def __init__(self, state: GuestState, scenario: str, stop: threading.Event):
        super().__init__(daemon=True)
        self.state = state
        self.stop = stop
        self.lock = threading.Lock()
        self.scenario = scenario
        self.fixture: Path | None = None
        self.session_id = "preview-" + secrets.token_hex(4)
        self.tick = 0
        self.phase_started = time.monotonic()

    def set_scenario(self, scenario: str) -> None:
        if scenario not in PREVIEW_SCENARIOS:
            raise ValueError("unknown preview scenario")
        with self.lock:
            self.scenario = scenario
            self.fixture = None
            self.session_id = "preview-" + secrets.token_hex(4)
            self.tick = 0
            self.phase_started = time.monotonic()

    def set_fixture(self, name: str) -> None:
        path = fixture_path(name)
        with self.lock:
            self.scenario = "fixture"
            self.fixture = path
            self.session_id = "preview-" + secrets.token_hex(4)
            self.tick = 0
            self.phase_started = time.monotonic()

    def effective(self) -> str:
        """Resolve ``cycle`` into the concrete phase for this moment."""
        with self.lock:
            scenario = self.scenario
            elapsed = time.monotonic() - self.phase_started
        if scenario != "cycle":
            return scenario
        # off for 20 s, active for 60 s, then silence long enough to expire, then repeat.
        if elapsed < 20:
            return "off"
        if elapsed < 80:
            return "active"
        if elapsed < 140:
            return "stale"
        with self.lock:
            self.phase_started = time.monotonic()
            self.session_id = "preview-" + secrets.token_hex(4)
        return "off"

    def run(self) -> None:
        while not self.stop.is_set():
            phase = self.effective()
            if phase == "fixture" and self.fixture is not None:
                self.state.receive(fixture_presentation(self.fixture, self.session_id))
            elif phase == "active":
                self.state.receive(synthetic_presentation(True, self.session_id, self.tick))
            elif phase == "off":
                self.state.receive(synthetic_presentation(False, self.session_id, self.tick))
            elif phase == "stale" and self.tick == 0:
                self.state.receive(synthetic_presentation(True, self.session_id, self.tick))
            self.tick += 1
            if self.stop.wait(10):
                break


PREVIEW_INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Porchlight guest screen preview</title><link rel="stylesheet" href="guest/guest.css"></head>
<body class="preview-body"><main class="preview">
<div class="lamp"><img src="icon-round.png" alt=""></div>
<h1>Hosting Guests preview</h1>
<p>Synthetic data only. The real screen is opened by Home Assistant on the TV with its private access link.</p>
<p><a class="preview-link" href="guest/#t=%(token)s">Open the guest screen</a></p>
<p class="preview-scenarios">Scenario: <a href="preview/scenario/active">active</a> \u00b7 <a href="preview/scenario/off">off</a> \u00b7 <a href="preview/scenario/stale">stale</a> \u00b7 <a href="preview/scenario/cycle">cycle</a></p>
<p class="preview-scenarios">Home Assistant fixtures: %(fixtures)s</p>
</main></body></html>
"""


class PreviewHandler(GuestScreenHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/":
            links = " \u00b7 ".join(f'<a href="preview/fixture/{name}">{name}</a>' for name in fixture_names()) or "none found"
            body = (PREVIEW_INDEX % {"token": PREVIEW_TOKEN, "fixtures": links}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", SCREEN_CSP)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return
        if path.startswith("/preview/scenario/") or path.startswith("/preview/fixture/"):
            kind, name = path[len("/preview/"):].split("/", 1)
            try:
                if kind == "scenario":
                    self.server.feeder.set_scenario(name)
                else:
                    self.server.feeder.set_fixture(name)
            except ValueError:
                self.reply(404, {"error": "not_found"})
                return
            self.redirect(f"{SCREEN_PATH}#t={PREVIEW_TOKEN}")
            return
        super().do_GET()


class PreviewServer(GuestScreenServer):
    def __init__(self, address, state: GuestState, feeder: PreviewFeeder):
        self.feeder = feeder
        self.state = state
        ThreadingHTTPServer.__init__(self, address, PreviewHandler)


def run_preview(host: str, port: int, scenario: str, fixture: str | None = None) -> int:
    state = GuestState(json.loads(json.dumps(PREVIEW_CONFIG)))
    stop = threading.Event()
    feeder = PreviewFeeder(state, scenario, stop)
    if fixture:
        feeder.set_fixture(fixture)
    server = PreviewServer((host, port), state, feeder)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    feeder.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"guest screen preview: http://{host}:{port}/  (scenario: {scenario})", flush=True)
    try:
        while not stop.wait(0.5):
            pass
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="porchlight-guest-screen")
    parser.add_argument("--preview", action="store_true", help="Serve the screen with synthetic presentation data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--scenario", choices=PREVIEW_SCENARIOS, default="active")
    parser.add_argument("--fixture", default="", help="Replay examples/guest-mode/fixtures/presentation.<name>.json")
    args = parser.parse_args()
    if not args.preview:
        parser.error("the appliance screen is served by porchlight-guest; use --preview for synthetic data")
    return run_preview(args.host, args.port, args.scenario, args.fixture or None)


if __name__ == "__main__":
    raise SystemExit(main())
