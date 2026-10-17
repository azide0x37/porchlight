"""Bounded Mosquitto adapter; subscribes only to the guest presentation topic."""
from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .config import load_config, load_env_file
from .guest import GuestHTTPServer, GuestState, MAX_PAYLOAD, load_guest_config
from .settings import validate_host, validate_port, validate_topic_part

MAX_FRAME = MAX_PAYLOAD * 6 + 2048  # JSON escaping in mosquitto_sub %j.


class GuestMQTT:
    def __init__(self, state, settings, runtime: Path, stop: threading.Event):
        self.state, self.settings, self.runtime, self.stop = state, settings, runtime, stop
        self.base = validate_topic_part(settings.get("HA_BASE_TOPIC", "porchlight"), "base_topic")
        self.topic = self.base + "/guest/presentation"
        self.pub = settings.get("MOSQUITTO_PUB", "mosquitto_pub")
        self.sub = settings.get("MOSQUITTO_SUB", "mosquitto_sub")
        self.environment = None

    def options(self):
        host = validate_host(self.settings.get("MQTT_HOST", ""))
        if not host:
            raise ValueError("mqtt_host_required")
        values = [("-h", host), ("-p", str(validate_port(self.settings.get("MQTT_PORT", 1883))))]
        username, password = self.settings.get("MQTT_USERNAME", ""), self.settings.get("MQTT_PASSWORD", "")
        if not username or not password:
            if self.settings.get("GUEST_MQTT_ALLOW_ANONYMOUS") != "1":
                raise ValueError("guest_authenticated_mqtt_required")
        else:
            values += [("-u", username), ("-P", password)]
        # Certificate verification stays on; no arbitrary arguments from MQTT or JSON.
        for setting, option in (("MQTT_CAFILE", "--cafile"), ("MQTT_CERTFILE", "--cert"), ("MQTT_KEYFILE", "--key")):
            if self.settings.get(setting):
                values.append((option, self.settings[setting]))
        if any("\n" in value or "\r" in value or "\x00" in value for _, value in values):
            raise ValueError("invalid_mqtt_option")
        return "".join(f"{option} {value}\n" for option, value in values)

    def publish(self, suffix, value, retain=False):
        payload = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
        command = [self.pub, "-t", self.base + suffix, "-s", "-q", "1"]
        if retain:
            command.append("-r")
        try:
            result = subprocess.run(command, input=payload.encode(), env=self.environment,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def consume(self, frame):
        # Envelope can be larger than the contract; bound both before decoding.
        if len(frame) > MAX_FRAME:
            self.state.disconnect()
            return
        try:
            envelope = json.loads(frame)
            if not isinstance(envelope, dict) or envelope.get("topic") != self.topic:
                raise ValueError("invalid_envelope")
            # Mosquitto 2.0 emits 0/1; 2.1 emits JSON false/true.
            if type(envelope.get("retain")) not in (bool, int) or envelope["retain"] not in (0, 1):
                raise ValueError("invalid_envelope")
            payload = envelope.get("payload")
            if not isinstance(payload, str):
                raise ValueError("invalid_payload")
            self.state.receive(payload.encode(), retained=envelope["retain"] != 0)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            self.state.receive(b"{}")

    def save_status(self):
        status = self.state.status()
        destination = self.runtime / "status.json"
        fd, name = tempfile.mkstemp(prefix=".status-", dir=self.runtime)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(status, output)
            os.replace(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return status

    def run(self):
        if not shutil.which(self.pub) or not shutil.which(self.sub):
            raise ValueError("mosquitto_clients_required")
        options = self.options()
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix="mqtt-", dir=self.runtime) as config_home:
            for name in ("mosquitto_pub", "mosquitto_sub"):
                path = Path(config_home) / name
                path.write_text(options)
                path.chmod(0o600)
            self.environment = {**os.environ, "XDG_CONFIG_HOME": config_home}
            delay = 1
            try:
                while not self.stop.is_set():
                    self.state.disconnect()
                    self.save_status()
                    self.publish("/guest/availability", "offline", retain=True)
                    # MQTT 5 preserves publisher retain flags and bounds broker packets.
                    command = [self.sub, "-V", "mqttv5", "--retain-as-published", "-F", "%j",
                               "-q", "1", "-k", "15", "-t", self.topic,
                               "-D", "CONNECT", "maximum-packet-size", str(MAX_PAYLOAD + 1024),
                               "--will-topic", self.base + "/guest/availability", "--will-payload", "offline",
                               "--will-qos", "1", "--will-retain"]
                    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          env=self.environment) as process:
                        try:
                            self.read_stream(process)
                        finally:
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                    self.state.disconnect()
                    self.save_status()
                    if self.stop.wait(delay):
                        break
                    delay = min(30, delay * 2)
            finally:
                self.state.disconnect()
                self.save_status()
                self.publish("/guest/availability", "offline", retain=True)

    def read_stream(self, process):
        buffer = b""
        next_status = 0
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while not self.stop.is_set() and process.poll() is None:
                if selector.select(timeout=0.25):
                    chunk = os.read(process.stdout.fileno(), 8192)
                    if not chunk:
                        return
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        self.consume(line)
                    if len(buffer) > MAX_FRAME:
                        self.state.disconnect()
                        return
                if time.monotonic() >= next_status:
                    status = self.save_status()
                    available = "online" if status["fresh"] else "offline"
                    if not self.publish("/guest/status", status) or not self.publish("/guest/availability", available, retain=True):
                        self.state.disconnect()
                    next_status = time.monotonic() + 5


def main():
    parser = argparse.ArgumentParser(prog="porchlight-guest")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate local configuration without connecting")
    args = parser.parse_args()
    config = load_config(apply=args.apply)
    path = config.config_dir / "guest.json"
    try:
        local = load_guest_config(path)
        if not local["enabled"]:
            print("guest backend disabled")
            return 0
        settings = {**load_env_file(config.config_dir / "porchlight.mqtt.env"),
                    **load_env_file(config.config_dir / "guest.env"), **os.environ}
        if settings.get("HA_MQTT_ENABLE", "0") != "1":
            raise ValueError("mqtt_disabled")
        state, stop = GuestState(local), threading.Event()
        adapter = GuestMQTT(state, settings, config.state_dir / "guest", stop)
        adapter.options()
        if args.check:
            print("guest configuration valid; UI and live acceptance pending")
            return 0
        server = GuestHTTPServer((settings.get("GUEST_WEB_HOST", "127.0.0.1"), int(settings.get("GUEST_WEB_PORT", "8766"))), state)
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter.run()
        finally:
            stop.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        # Never echo config values or exception strings containing credentials.
        print("guest backend configuration or transport failure", file=__import__("sys").stderr)
        return 1
