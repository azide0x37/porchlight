from __future__ import annotations

import argparse
import json
import os
import subprocess
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import load_config
from .settings import (
    masked_mqtt_settings,
    mqtt_settings,
    setup_status,
    update_mqtt_settings,
    validate_host,
    validate_port,
    validate_topic_part,
    wifi_networks,
    wifi_status,
)


class PorchlightHTTPRequestHandler(SimpleHTTPRequestHandler):
    server: "PorchlightHTTPServer"

    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.endswith((".html", ".css", ".js", ".json", ".webmanifest")) or path == "/" or path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        elif path.endswith((".png", ".svg", ".woff2")):
            self.send_header("Cache-Control", "public, max-age=604800")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/api/setup/status":
            self.write_json(self.server.setup_payload())
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            payload = self.read_json_body()
            if path == "/api/setup/mqtt":
                self.write_json({"mqtt": update_mqtt_settings(self.server.config.config_dir, payload)})
                self.server.request_apply("restart_bridge")
            elif path == "/api/setup/mqtt/test":
                self.write_json(self.server.test_mqtt(payload))
            elif path == "/api/setup/wifi":
                self.write_json(self.server.configure_wifi(payload))
            elif path == "/api/setup/finish":
                self.write_json(self.server.finish_setup())
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "unknown endpoint")
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except subprocess.TimeoutExpired:
            self.write_json({"ok": False, "error": "operation timed out"}, HTTPStatus.GATEWAY_TIMEOUT)
        except OSError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json_body(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length > 8192:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def write_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PorchlightHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler, config, apply: bool):
        super().__init__(server_address, handler)
        self.config = config
        self.apply = apply

    def setup_payload(self) -> dict[str, object]:
        return {
            "setup": setup_status(self.config.config_dir),
            "mqtt": masked_mqtt_settings(self.config.config_dir),
            "wifi": self.wifi_payload(),
        }

    def wifi_payload(self) -> dict[str, object]:
        payload = wifi_status() if self.apply else {"available": False, "connected": False, "ssid": "", "message": "mock mode"}
        payload["networks"] = wifi_networks()
        return payload

    def configure_wifi(self, payload: dict[str, object]) -> dict[str, object]:
        status = setup_status(self.config.config_dir)
        if not status["appliance_mode"]:
            raise ValueError("Wi-Fi setup is only available in appliance mode")
        ssid = str(payload.get("ssid") or "").strip()
        password = str(payload.get("password") or "")
        if not ssid or len(ssid) > 32:
            raise ValueError("Wi-Fi SSID must be 1-32 characters")
        if password and len(password) < 8:
            raise ValueError("Wi-Fi password must be at least 8 characters")
        if not self.apply:
            self.write_runtime_request("wifi_configured")
            return {"ok": True, "wifi": {"available": False, "connected": False, "ssid": ssid, "message": "mock mode"}}
        command = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            command.extend(["password", password])
        result = subprocess.run(command, text=True, capture_output=True, timeout=40, check=False)
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "failed to configure Wi-Fi")
        return {"ok": True, "wifi": wifi_status()}

    def test_mqtt(self, payload: dict[str, object]) -> dict[str, object]:
        saved = mqtt_settings(self.config.config_dir)
        current = dict(masked_mqtt_settings(self.config.config_dir))
        candidate = {**current, **payload}
        host = validate_host(candidate.get("host"))
        port = str(validate_port(candidate.get("port") or 1883))
        topic = validate_topic_part(candidate.get("base_topic") or "porchlight", "base_topic") + "/setup/test"
        username = str(candidate.get("username") or "")
        password = str(payload.get("password") if "password" in payload else saved.get("MQTT_PASSWORD", ""))
        if not host:
            raise ValueError("MQTT host is required")
        if not self.apply:
            return {"ok": True, "message": "mock publish accepted"}
        command = ["mosquitto_pub", "-h", host, "-p", port, "-t", topic, "-m", "porchlight setup test"]
        if username:
            command.extend(["-u", username, "-P", password])
        result = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or "MQTT publish failed"}
        return {"ok": True, "message": "test publish sent"}

    def finish_setup(self) -> dict[str, object]:
        status = setup_status(self.config.config_dir)
        if not status["appliance_mode"]:
            raise ValueError("setup completion is only available in appliance mode")
        self.config.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config.config_dir / "setup-complete").write_text("true\n", encoding="utf-8")
        self.request_apply("shutdown_setup_ap")
        return {"ok": True, "setup": setup_status(self.config.config_dir)}

    def request_apply(self, action: str) -> None:
        if action not in {"restart_bridge", "shutdown_setup_ap"}:
            raise ValueError("unsupported setup action")
        self.write_runtime_request(action)

    def write_runtime_request(self, action: str) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        (self.config.state_dir / "setup-action").write_text(action + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="porchlight-web")
    parser.add_argument("--apply", action="store_true", help="Use real appliance paths")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(apply=args.apply)
    host = os.environ.get("PORCHLIGHT_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("PORCHLIGHT_WEB_PORT", "8765"))
    handler = partial(PorchlightHTTPRequestHandler, directory=str(config.www_dir))
    server = PorchlightHTTPServer((host, port), handler, config, args.apply)
    server.serve_forever()
    return 0
