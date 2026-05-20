from __future__ import annotations

import os
import re
import socket
import stat
import subprocess
import tempfile
from pathlib import Path

from .config import bool_value, load_env_file


MQTT_KEYS = (
    "HA_MQTT_ENABLE",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "MQTT_PUBLISH_TIMEOUT_SECONDS",
    "HA_DISCOVERY_PREFIX",
    "HA_NODE_ID",
    "HA_DEVICE_NAME",
    "HA_BASE_TOPIC",
)

DEFAULT_MQTT = {
    "HA_MQTT_ENABLE": "1",
    "MQTT_HOST": "127.0.0.1",
    "MQTT_PORT": "1883",
    "MQTT_USERNAME": "",
    "MQTT_PASSWORD": "",
    "MQTT_PUBLISH_TIMEOUT_SECONDS": "5",
    "HA_DISCOVERY_PREFIX": "homeassistant",
    "HA_NODE_ID": "porchlight",
    "HA_DEVICE_NAME": "Porchlight LAN Directory",
    "HA_BASE_TOPIC": "porchlight",
}

HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
TOPIC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_/-]*$")


def atomic_write_env(path: Path, values: dict[str, str], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    lines: list[str] = []

    for raw in existing:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            lines.append(raw)
            continue
        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in remaining:
            lines.append(f"{key}={quote_env(remaining.pop(key))}")
        else:
            lines.append(raw)

    for key, value in remaining.items():
        lines.append(f"{key}={quote_env(value)}")

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write("\n".join(lines).rstrip() + "\n")
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def quote_env(value: str) -> str:
    text = str(value)
    if text == "" or re.search(r"\s|#|['\"]", text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def mqtt_settings(config_dir: Path) -> dict[str, str]:
    values = dict(DEFAULT_MQTT)
    values.update(load_env_file(config_dir / "porchlight.mqtt.env"))
    return {key: values.get(key, "") for key in MQTT_KEYS}


def masked_mqtt_settings(config_dir: Path) -> dict[str, object]:
    values = mqtt_settings(config_dir)
    return {
        "enabled": bool_value(values.get("HA_MQTT_ENABLE"), False),
        "host": values.get("MQTT_HOST", ""),
        "port": int(values.get("MQTT_PORT") or "1883"),
        "username": values.get("MQTT_USERNAME", ""),
        "password_set": bool(values.get("MQTT_PASSWORD")),
        "publish_timeout_seconds": int(values.get("MQTT_PUBLISH_TIMEOUT_SECONDS") or "5"),
        "discovery_prefix": values.get("HA_DISCOVERY_PREFIX", "homeassistant"),
        "node_id": values.get("HA_NODE_ID", "porchlight"),
        "device_name": values.get("HA_DEVICE_NAME", "Porchlight LAN Directory"),
        "base_topic": values.get("HA_BASE_TOPIC", "porchlight"),
    }


def update_mqtt_settings(config_dir: Path, payload: dict[str, object]) -> dict[str, object]:
    existing = mqtt_settings(config_dir)
    updates: dict[str, str] = {}

    if "enabled" in payload:
        updates["HA_MQTT_ENABLE"] = "1" if bool(payload["enabled"]) else "0"
    if "host" in payload:
        updates["MQTT_HOST"] = validate_host(payload["host"])
    if "port" in payload:
        updates["MQTT_PORT"] = str(validate_port(payload["port"]))
    if "username" in payload:
        updates["MQTT_USERNAME"] = str(payload["username"] or "").strip()
    if "password" in payload:
        updates["MQTT_PASSWORD"] = str(payload["password"] or "")
    if "publish_timeout_seconds" in payload:
        updates["MQTT_PUBLISH_TIMEOUT_SECONDS"] = str(validate_timeout(payload["publish_timeout_seconds"]))
    if "discovery_prefix" in payload:
        updates["HA_DISCOVERY_PREFIX"] = validate_topic_part(payload["discovery_prefix"], "discovery_prefix")
    if "node_id" in payload:
        updates["HA_NODE_ID"] = validate_token(payload["node_id"], "node_id")
    if "device_name" in payload:
        updates["HA_DEVICE_NAME"] = str(payload["device_name"] or "").strip() or DEFAULT_MQTT["HA_DEVICE_NAME"]
    if "base_topic" in payload:
        updates["HA_BASE_TOPIC"] = validate_topic_part(payload["base_topic"], "base_topic")

    merged = {**existing, **updates}
    atomic_write_env(config_dir / "porchlight.mqtt.env", {key: merged[key] for key in MQTT_KEYS}, 0o600)
    return masked_mqtt_settings(config_dir)


def validate_host(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 253 or not HOST_RE.match(text):
        raise ValueError("MQTT host must be a hostname or IP address")
    return text


def validate_port(value: object) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("MQTT port must be a number") from exc
    if port < 1 or port > 65535:
        raise ValueError("MQTT port must be between 1 and 65535")
    return port


def validate_timeout(value: object) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("MQTT publish timeout must be a number") from exc
    if timeout < 1 or timeout > 60:
        raise ValueError("MQTT publish timeout must be between 1 and 60 seconds")
    return timeout


def validate_token(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 64 or not TOKEN_RE.match(text):
        raise ValueError(f"{label} must contain only letters, numbers, underscores, or hyphens")
    return text


def validate_topic_part(value: object, label: str) -> str:
    text = str(value or "").strip().strip("/")
    if not text or len(text) > 128 or not TOPIC_RE.match(text) or "//" in text:
        raise ValueError(f"{label} must be a valid MQTT topic prefix")
    return text


def setup_settings(config_dir: Path) -> dict[str, str]:
    return load_env_file(config_dir / "setup.env")


def setup_status(config_dir: Path) -> dict[str, object]:
    values = setup_settings(config_dir)
    return {
        "appliance_mode": bool_value(values.get("PORCHLIGHT_APPLIANCE_MODE"), False),
        "setup_complete": (config_dir / "setup-complete").exists(),
        "mdns_name": values.get("PORCHLIGHT_MDNS_NAME", default_mdns_name()),
        "setup_ssid": values.get("PORCHLIGHT_SETUP_SSID", ""),
    }


def default_mdns_name() -> str:
    host = socket.gethostname().split(".")[0] or "porchlight"
    return f"{host}.local"


def wifi_status() -> dict[str, object]:
    if not shutil_which("nmcli"):
        return {"available": False, "connected": False, "ssid": "", "message": "NetworkManager is not installed"}
    result = subprocess.run(
        ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return {"available": True, "connected": False, "ssid": "", "message": result.stderr.strip()}
    for line in result.stdout.splitlines():
        active, _, ssid = line.partition(":")
        if active == "yes":
            return {"available": True, "connected": True, "ssid": ssid, "message": ""}
    return {"available": True, "connected": False, "ssid": "", "message": ""}


def wifi_networks() -> list[dict[str, object]]:
    mock = os.environ.get("PORCHLIGHT_MOCK_WIFI_SSIDS", "")
    if mock:
        return [{"ssid": ssid.strip(), "signal": None, "security": ""} for ssid in mock.split(",") if ssid.strip()]
    if not shutil_which("nmcli"):
        return []
    result = subprocess.run(
        ["nmcli", "-t", "-f", "ssid,signal,security", "dev", "wifi", "list", "--rescan", "yes"],
        text=True,
        capture_output=True,
        timeout=12,
        check=False,
    )
    if result.returncode != 0:
        return []
    networks: dict[str, dict[str, object]] = {}
    for line in result.stdout.splitlines():
        ssid, signal, security = split_nmcli_fields(line)
        if not ssid:
            continue
        try:
            parsed_signal = int(signal)
        except ValueError:
            parsed_signal = None
        existing = networks.get(ssid)
        if existing and parsed_signal is not None and existing.get("signal") is not None and int(existing["signal"]) >= parsed_signal:
            continue
        networks[ssid] = {"ssid": ssid, "signal": parsed_signal, "security": security}
    return sorted(networks.values(), key=lambda item: (-(item.get("signal") or 0), str(item.get("ssid") or "")))


def split_nmcli_fields(line: str) -> tuple[str, str, str]:
    fields: list[str] = []
    current = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":" and len(fields) < 2:
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    while len(fields) < 3:
        fields.append("")
    return fields[0], fields[1], fields[2]


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        try:
            mode = candidate.stat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISREG(mode) and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
