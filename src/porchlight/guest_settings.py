"""Owner-side editing of ``/etc/porchlight/guest.json`` from the dashboard Settings view.

The dashboard writes the guest screen's Wi-Fi, welcome copy, voice examples, climate
allowlist, and access token. Every write is validated with the guest backend's own
``load_guest_config`` before it replaces the live file, so the dashboard can never leave a
configuration the ``porchlight-guest`` service would refuse. Responses are masked: the
Wi-Fi password and access token are never echoed, except a freshly issued token exactly once.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import bool_value, load_env_file
from .guest import load_guest_config
from .guest_media import PLAYER, validate_jam
from .guest_wifi import GuestWifi
from .settings import atomic_write_env

GUEST_FILE = "guest.json"
GUEST_ENV = "guest.env"
EXAMPLE = Path(__file__).resolve().parents[2] / "etc" / "guest.json.example"
VOICE_CATEGORIES = ("lights", "music", "blinds")
CLIMATE_RE = re.compile(r"^climate\.[a-z0-9_]{1,100}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
SECURITY = ("WPA", "nopass")
DEFAULT_PRESENTATION = {"title": "A few things for your stay", "stale_after_seconds": 45, "exit_policy": "neutral_screen_keep_tv_on"}
DEFAULTS = {
    "schema_version": 1,
    "enabled": False,
    "welcome": "Welcome to {home}, make yourself at home",
    "wifi": None,
    "alexa": {"lights": [], "music": [], "blinds": []},
    "presentation": dict(DEFAULT_PRESENTATION),
    "access_token": "",
    "allowed_climate_entities": [],
}
REJECTIONS = {
    "guest_access_token_required": "an access token is required while the guest screen is enabled",
    "guest_climate_allowlist": "climate entities must look like climate.guest_room (at most eight)",
    "guest_presentation_policy": "presentation policy must stay at 45 seconds and neutral_screen_keep_tv_on",
    "guest_voice_examples": "voice examples allow up to three phrases for lights, music, and blinds",
    "guest_wifi": "guest Wi-Fi needs a name of at most 32 bytes and a supported security type",
    "guest_wifi_password": "guest Wi-Fi password must be 8-63 characters",
    "guest_open_wifi_password": "an open network cannot have a password",
    "invalid_text": "text fields must be non-empty, within their length limits, and free of control characters",
}


def default_config() -> dict:
    try:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return json.loads(json.dumps(DEFAULTS))


def read_guest_config(config_dir: Path) -> dict | None:
    path = config_dir / GUEST_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def guest_listener(config_dir: Path) -> dict[str, object]:
    env = load_env_file(config_dir / GUEST_ENV)
    try:
        port = int(env.get("GUEST_WEB_PORT", "8766"))
    except ValueError:
        port = 8766
    return {"guest_host": env.get("GUEST_WEB_HOST", "127.0.0.1"), "guest_port": port}


def masked_guest_settings(config_dir: Path) -> dict[str, object]:
    data = read_guest_config(config_dir) or default_config()
    wifi = data.get("wifi") if isinstance(data.get("wifi"), dict) else None
    alexa = data.get("alexa") if isinstance(data.get("alexa"), dict) else {}
    presentation = data.get("presentation") if isinstance(data.get("presentation"), dict) else {}
    token = data.get("access_token")
    env = load_env_file(config_dir / GUEST_ENV)
    return {
        "configured": (config_dir / GUEST_FILE).is_file(),
        "enabled": bool(data.get("enabled") is True),
        "welcome": str(data.get("welcome") or ""),
        "home_name": str(data.get("home_name") or ""),
        "title": str(presentation.get("title") or ""),
        "wifi": {
            "ssid": str(wifi.get("ssid") or "") if wifi else "",
            "security": str(wifi.get("security") or "WPA") if wifi else "WPA",
            "hidden": bool(wifi.get("hidden")) if wifi else False,
            "password_set": bool(wifi.get("password")) if wifi else False,
        },
        "alexa": {
            category: [str(item) for item in alexa.get(category, []) if isinstance(item, str)][:3]
            for category in VOICE_CATEGORIES
        },
        "allowed_climate_entities": [str(item) for item in data.get("allowed_climate_entities", []) if isinstance(item, str)],
        "allowed_spotify_entities": [str(item) for item in data.get("allowed_spotify_entities", []) if isinstance(item, str)],
        "spotify_jam_set": bool(data.get("spotify_jam")),
        "ha": {"url": env.get("GUEST_HA_URL", ""), "token_set": bool(env.get("GUEST_HA_TOKEN")),
               "wifi_qr_entity": env.get("GUEST_WIFI_QR_ENTITY", ""), "wifi_ssid": env.get("GUEST_WIFI_SSID", "")},
        "access_token_set": isinstance(token, str) and bool(TOKEN_RE.fullmatch(token)),
        **guest_listener(config_dir),
    }


def clean_text(value: object, limit: int, label: str) -> str:
    text = str(value if value is not None else "").strip()
    if not text or len(text) > limit or any(ord(char) < 32 for char in text):
        raise ValueError(f"{label} must be 1-{limit} characters without control characters")
    return text


def phrase_list(value: object, label: str) -> list[str]:
    if isinstance(value, str):
        items = value.replace("\r", "").split("\n")
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        raise ValueError(f"{label} must be a list of phrases")
    phrases = [item.strip() for item in items if item and item.strip()]
    if len(phrases) > 3:
        raise ValueError(f"{label} allows at most three phrases")
    return [clean_text(item, 180, label) for item in phrases]


def climate_list(value: object) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[\s,]+", value.strip())
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        raise ValueError("climate entities must be a list")
    entities = [item.strip() for item in items if item and item.strip()]
    if len(entities) > 8:
        raise ValueError("at most eight climate entities are allowed")
    for entity in entities:
        if not CLIMATE_RE.fullmatch(entity):
            raise ValueError(f"unsupported climate entity id: {entity}")
    return entities


def apply_wifi(data: dict, payload: dict) -> None:
    existing = data.get("wifi") if isinstance(data.get("wifi"), dict) else {}
    ssid = str(payload.get("ssid", existing.get("ssid", "")) or "").strip()
    if not ssid:
        data["wifi"] = None
        return
    if len(ssid) > 32 or len(ssid.encode("utf-8")) > 32 or any(ord(char) < 32 for char in ssid):
        raise ValueError("guest Wi-Fi name must be at most 32 bytes")
    security = str(payload.get("security", existing.get("security", "WPA")) or "WPA")
    if security not in SECURITY:
        raise ValueError("guest Wi-Fi security must be WPA or nopass")
    hidden = bool_value(payload.get("hidden", existing.get("hidden", False)), False)
    password = str(existing.get("password") or "")
    if "password" in payload and str(payload["password"]) != "":
        password = str(payload["password"])
    if security == "nopass":
        password = ""
    elif not 8 <= len(password) <= 63 or any(ord(char) < 32 for char in password):
        raise ValueError("guest Wi-Fi password must be 8-63 characters")
    data["wifi"] = {"ssid": ssid, "security": security, "password": password, "hidden": hidden}


def write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        try:
            load_guest_config(Path(tmp_name))
        except ValueError as exc:
            code = str(exc)
            raise ValueError(REJECTIONS.get(code, f"guest configuration rejected: {code}")) from exc
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def update_guest_settings(config_dir: Path, payload: dict[str, object]) -> dict[str, object]:
    data = read_guest_config(config_dir) or default_config()
    data["schema_version"] = 1
    presentation = data.get("presentation") if isinstance(data.get("presentation"), dict) else {}
    data["presentation"] = {**DEFAULT_PRESENTATION, **presentation, "stale_after_seconds": 45, "exit_policy": "neutral_screen_keep_tv_on"}
    if "enabled" in payload:
        data["enabled"] = bool_value(payload["enabled"], False)
    if "welcome" in payload:
        data["welcome"] = clean_text(payload["welcome"], 200, "welcome line")
    if "home_name" in payload:
        home_name = str(payload["home_name"] or "").strip()
        if home_name:
            data["home_name"] = clean_text(home_name, 60, "home name")
        else:
            data.pop("home_name", None)
    if "title" in payload:
        data["presentation"]["title"] = clean_text(payload["title"], 120, "subtitle")
    if any(key in payload for key in ("ssid", "security", "hidden", "password")):
        apply_wifi(data, payload)
    if "alexa" in payload:
        raw = payload["alexa"] if isinstance(payload["alexa"], dict) else {}
        current = data.get("alexa") if isinstance(data.get("alexa"), dict) else {}
        alexa = {}
        for category in VOICE_CATEGORIES:
            if category in raw:
                phrases = phrase_list(raw[category], f"{category} phrases")
            else:
                phrases = [item for item in current.get(category, []) if isinstance(item, str)]
            if phrases:
                alexa[category] = phrases
        data["alexa"] = alexa
    if "allowed_climate_entities" in payload:
        data["allowed_climate_entities"] = climate_list(payload["allowed_climate_entities"])
    if "allowed_spotify_entities" in payload:
        players = payload["allowed_spotify_entities"]
        if not isinstance(players, list) or len(players) > 8 or any(not isinstance(x, str) or not PLAYER.fullmatch(x) for x in players):
            raise ValueError("Spotify players must be a list of at most eight media_player entity IDs")
        data["allowed_spotify_entities"] = players
    if "spotify_jam" in payload:
        data["spotify_jam"] = validate_jam(payload["spotify_jam"])
    token = data.get("access_token") if isinstance(data.get("access_token"), str) else ""
    issued = None
    if bool_value(payload.get("rotate_token"), False) or (data.get("enabled") is True and not TOKEN_RE.fullmatch(token or "")):
        issued = secrets.token_urlsafe(48)
        data["access_token"] = issued
    elif not token:
        data["access_token"] = ""
    write_private_json(config_dir / GUEST_FILE, data)
    result = masked_guest_settings(config_dir)
    if issued:
        result["access_token_once"] = issued
    return result


def bind_jam_invite(payload, receiver, now):
    """Bind a host's new invite to a recent, enabled receiver session."""
    if "spotify_jam_url" not in payload:
        return payload
    if not payload["spotify_jam_url"]:
        return {**payload, "spotify_jam": None}
    try:
        generated = datetime.fromisoformat(receiver["generated_at"].replace("Z", "+00:00")).timestamp()
        if not receiver.get("enabled") or not receiver.get("fresh") or not -5 <= now - generated < 45:
            raise ValueError("inactive")
        jam = {"url": payload["spotify_jam_url"], "session_id": receiver["session_id"],
               "expires_at": datetime.fromtimestamp(now + 4 * 3600, timezone.utc).isoformat()}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Start Guest Mode and wait for fresh receiver data before adding a Jam invite") from exc
    return {**payload, "spotify_jam": validate_jam(jam)}


def update_guest_ha_settings(config_dir, payload):
    env = load_env_file(config_dir / GUEST_ENV)
    for field, key in (("url", "GUEST_HA_URL"), ("wifi_qr_entity", "GUEST_WIFI_QR_ENTITY"), ("wifi_ssid", "GUEST_WIFI_SSID")):
        if field in payload:
            env[key] = str(payload[field]).strip()
    if payload.get("token"):
        env["GUEST_HA_TOKEN"] = str(payload["token"]).strip()
    if bool_value(payload.get("clear_token"), False):
        env["GUEST_HA_TOKEN"] = ""
        env["GUEST_HA_URL"] = ""
    if env.get("GUEST_HA_URL"):
        GuestWifi(env, None, threading.Event())  # Validate only; never contact HA on save.
    atomic_write_env(config_dir / GUEST_ENV, env, 0o600)
    return masked_guest_settings(config_dir)
