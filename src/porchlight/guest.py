"""Guest presentation contract. No scanner, HA service, or TV control access."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_PAYLOAD = 16 * 1024
FRESH_SECONDS = 45
ACK_SECONDS = 20
SESSION = re.compile(r"^[A-Za-z0-9_.:+-]{1,100}$")
CLIMATE = re.compile(r"^climate\.[a-z0-9_]{1,100}$")
MODES = {"off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"}
ACTIONS = {"off", "heating", "cooling", "drying", "idle", "fan", "preheating", "defrosting"}


def strict_json(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_PAYLOAD:
        raise ValueError("payload_size")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result
    try:
        def reject_constant(_):
            raise ValueError("invalid_number")
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("invalid_object")
    return value


def text(value, limit=120):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_text")
    return value


def validate_presentation(raw: bytes, allowed: set[str], now: float) -> tuple[dict, float]:
    data = strict_json(raw)
    if set(data) != {"schema_version", "enabled", "generated_at", "session_id", "hvac"}:
        raise ValueError("invalid_fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or type(data["enabled"]) is not bool:
        raise ValueError("invalid_version_or_mode")
    if not SESSION.fullmatch(text(data["session_id"])):
        raise ValueError("invalid_session")
    try:
        stamp = datetime.fromisoformat(text(data["generated_at"], 50).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("timezone_required")
        timestamp = stamp.timestamp()
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid_timestamp") from exc
    if timestamp > now + 5 or now - timestamp >= FRESH_SECONDS:
        raise ValueError("stale_or_future")
    zones = data["hvac"]
    if not isinstance(zones, list) or len(zones) > 8 or (not data["enabled"] and zones):
        raise ValueError("invalid_hvac")
    seen = set()
    fields = {"id", "label", "available", "unit", "mode", "action", "current_temperature",
              "target_temperature", "target_temperature_low", "target_temperature_high"}
    for zone in zones:
        if not isinstance(zone, dict) or set(zone) != fields:
            raise ValueError("invalid_hvac_fields")
        entity = zone["id"]
        if not isinstance(entity, str) or entity not in allowed or entity in seen:
            raise ValueError("unapproved_climate")
        seen.add(entity)
        text(zone["label"], 80)
        if type(zone["available"]) is not bool or zone["unit"] not in ("°C", "°F"):
            raise ValueError("invalid_hvac_type")
        for field in ("current_temperature", "target_temperature", "target_temperature_low", "target_temperature_high"):
            value = zone[field]
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not -100 <= value <= 250):
                raise ValueError("invalid_temperature")
        if zone["mode"] is not None and zone["mode"] not in MODES:
            raise ValueError("invalid_mode")
        if zone["action"] is not None and zone["action"] not in ACTIONS:
            raise ValueError("invalid_action")
        low, high = zone["target_temperature_low"], zone["target_temperature_high"]
        if low is not None and high is not None and low > high:
            raise ValueError("invalid_range")
        if not zone["available"]:
            for field in fields - {"id", "label", "available", "unit"}:
                zone[field] = None
    return data, timestamp


def load_guest_config(path: Path) -> dict:
    if path.stat().st_mode & 0o077:
        raise ValueError("guest_config_permissions")
    data = strict_json(path.read_bytes())
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1 or type(data.get("enabled")) is not bool:
        raise ValueError("guest_config_version")
    if not data["enabled"]:
        return data
    token = data.get("access_token", "")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise ValueError("guest_access_token_required")
    allowed = data.get("allowed_climate_entities", [])
    if not isinstance(allowed, list) or len(allowed) > 8 or any(not isinstance(x, str) or not CLIMATE.fullmatch(x) for x in allowed):
        raise ValueError("guest_climate_allowlist")
    text(data.get("welcome"), 200)
    presentation = data.get("presentation", {})
    if not isinstance(presentation, dict):
        raise ValueError("guest_presentation_policy")
    if presentation.get("stale_after_seconds") != FRESH_SECONDS or presentation.get("exit_policy") != "neutral_screen_keep_tv_on":
        raise ValueError("guest_presentation_policy")
    text(presentation.get("title"), 120)
    alexa = data.get("alexa", {})
    if not isinstance(alexa, dict) or set(alexa) - {"lights", "music"}:
        raise ValueError("guest_voice_examples")
    for category in ("lights", "music"):
        commands = alexa.get(category, [])
        if not isinstance(commands, list) or len(commands) > 3:
            raise ValueError("guest_voice_examples")
        for command in commands:
            text(command, 180)
    wifi = data.get("wifi")
    if wifi is not None:
        if not isinstance(wifi, dict) or set(wifi) != {"ssid", "security", "password", "hidden"}:
            raise ValueError("guest_wifi")
        ssid = text(wifi.get("ssid"), 32)
        if len(ssid.encode()) > 32 or wifi.get("security") not in ("WPA", "nopass") or type(wifi.get("hidden")) is not bool:
            raise ValueError("guest_wifi")
        password = wifi.get("password", "")
        if wifi["security"] == "WPA":
            text(password, 63)
            if len(password) < 8:
                raise ValueError("guest_wifi_password")
        elif password:
            raise ValueError("guest_open_wifi_password")
    return data


def wifi_payload(wifi: dict) -> str:
    def escape(value):
        return "".join("\\" + c if c in '\\;,:"' else c for c in value)
    return f'WIFI:T:{wifi["security"]};S:{escape(wifi["ssid"])};P:{escape(wifi.get("password", ""))};H:{str(wifi["hidden"]).lower()};;'


class GuestState:
    def __init__(self, config: dict, wall=time.time, monotonic=time.monotonic):
        self.config, self.wall, self.monotonic = config, wall, monotonic
        self.lock = threading.RLock()
        self.data = None
        self.timestamp = float("-inf")
        self.deadline = 0.0
        self.started = 0.0
        self.ack_deadline = 0.0
        self.presentation_id = ""
        self.transport = False
        self.last_error = None
        self.rejected = 0

    def receive(self, payload: bytes, retained=False) -> bool:
        with self.lock:
            try:
                if retained:
                    raise ValueError("retained_snapshot")
                data, timestamp = validate_presentation(payload, set(self.config.get("allowed_climate_entities", [])), self.wall())
                if timestamp <= self.timestamp:
                    raise ValueError("out_of_order")
            except (ValueError, TypeError) as exc:
                self.last_error = str(exc) if isinstance(exc, ValueError) else "invalid_type"
                self.rejected += 1
                return False
            new_session = not self.fresh() or not self.data or data["session_id"] != self.data["session_id"] or data["enabled"] != self.data["enabled"]
            if new_session:
                self.presentation_id = secrets.token_urlsafe(24)
                self.ack_deadline = 0.0
                self.started = self.monotonic()
            self.data, self.timestamp = data, timestamp
            self.deadline = self.monotonic() + min(FRESH_SECONDS, FRESH_SECONDS - (self.wall() - timestamp))
            self.transport = True
            self.last_error = None
            return True

    def disconnect(self):
        with self.lock:
            self.transport = False
            self.deadline = self.ack_deadline = 0.0

    def fresh(self):
        return bool(self.transport and self.data and self.monotonic() < self.deadline and self.wall() - self.timestamp < FRESH_SECONDS)

    def status(self):
        with self.lock:
            fresh = self.fresh()
            enabled = bool(fresh and self.config["enabled"] and self.data["enabled"])
            state, error = "unavailable", "snapshot_unavailable"
            if fresh:
                if not enabled:
                    state, error = "off", None
                elif self.monotonic() < self.ack_deadline:
                    state, error = "active", None
                elif self.monotonic() - self.started < 30:
                    state, error = "starting", "presenter_pending"
                else:
                    state, error = "degraded", "presenter_missing"
            return {"schema_version": 1, "status": state, "enabled": enabled,
                    "session_id": self.data["session_id"] if self.data else None,
                    "generated_at": self.data["generated_at"] if self.data else None,
                    "fresh": fresh, "error": error, "last_rejection": self.last_error,
                    "rejected_messages": self.rejected,
                    "expires_in_seconds": max(0, int(self.deadline - self.monotonic())) if fresh else 0}

    def view(self):
        with self.lock:
            result = self.status()
            if not result["enabled"]:
                return result
            result.update({"presentation_id": self.presentation_id, "welcome": self.config["welcome"],
                           "title": self.config["presentation"]["title"], "hvac": self.data["hvac"],
                           "alexa": self.config.get("alexa", {}), "wifi": None})
            if self.config.get("wifi"):
                result["wifi"] = {**self.config["wifi"], "qr_payload": wifi_payload(self.config["wifi"])}
            return result

    def heartbeat(self, payload: dict):
        with self.lock:
            if set(payload) != {"session_id", "presentation_id", "visible"} or type(payload["visible"]) is not bool:
                raise ValueError("invalid_heartbeat")
            if not self.status()["enabled"] or payload["session_id"] != self.data["session_id"] or payload["presentation_id"] != self.presentation_id:
                raise ValueError("inactive_session")
            self.ack_deadline = self.monotonic() + ACK_SECONDS if payload["visible"] else 0.0
            return self.status()


class GuestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log paths, tokens, payloads, or guest credentials.

    def reply(self, code, payload):
        body = json.dumps(payload, allow_nan=False).encode()
        self.send_response(code)
        for key, value in {"Content-Type": "application/json", "Content-Length": str(len(body)),
                           "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                           "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'",
                           "Connection": "close"}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def authorized(self):
        expected = "Bearer " + self.server.state.config["access_token"]
        # No cookies, query-string credentials, CORS, or admin-route forwarding.
        return hmac.compare_digest(hashlib.sha256(self.headers.get("Authorization", "").encode()).digest(),
                                   hashlib.sha256(expected.encode()).digest())

    def do_GET(self):
        if self.path == "/healthz":
            self.reply(200, {"service": "porchlight-guest", "ui_available": False})
        elif self.path in ("/api/guest", "/api/guest/status"):
            if not self.authorized():
                self.reply(401, {"error": "unauthorized"})
            else:
                self.reply(200, self.server.state.view() if self.path == "/api/guest" else self.server.state.status())
        else:
            self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/api/guest/heartbeat":
            self.reply(404, {"error": "not_found"})
        elif not self.authorized():
            self.reply(401, {"error": "unauthorized"})
        else:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 512 or self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
                    raise ValueError("invalid_body")
                self.reply(200, self.server.state.heartbeat(strict_json(self.rfile.read(length))))
            except (ValueError, OSError):
                self.reply(400, {"error": "invalid_or_inactive_heartbeat"})


class GuestHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, state):
        self.state = state
        super().__init__(address, GuestHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address
