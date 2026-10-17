import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from porchlight.guest import validate_presentation


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node):
    result = {}
    for key, value in node.value:
        key = loader.construct_object(key)
        if key in result:
            raise ValueError("duplicate YAML key: " + key)
        result[key] = loader.construct_object(value)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


class HomeAssistantGuestContractTest(unittest.TestCase):
    def setUp(self):
        self.package = yaml.load((ROOT / "homeassistant/porchlight_guest.yaml").read_text(), Loader=UniqueLoader)
        self.environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        self.environment.filters.update(to_json=json.dumps, bool=bool, regex_match=lambda value, pattern: bool(re.match(pattern, value)))

    def test_templates_compile_and_hvac_snapshots_satisfy_receiver(self):
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)
        for source in strings(self.package):
            if "{{" in source or "{%" in source:
                self.environment.from_string(source)
        source = self.package["script"]["porchlight_guest_publish"]["sequence"][1]["data"]["payload"]
        now = datetime.now(timezone.utc)
        allowed = {"climate.living_room_thermostat", "climate.bedroom_ac", "climate.kitchen_ac"}
        scenarios = [
            (True, "cool", {"temperature": 72, "current_temperature": 73, "hvac_action": "cooling"}),
            (True, "heat_cool", {"target_temp_low": 68, "target_temp_high": 74, "hvac_action": "idle"}),
            (True, "off", {"current_temperature": 0, "hvac_action": "off"}),
            (True, "unavailable", {"current_temperature": 99, "temperature": 66}),
            (True, "unknown", {}), (False, "cool", {"temperature": 72}),
        ]
        for enabled, mode, attrs in scenarios:
            with self.subTest(enabled=enabled, mode=mode):
                raw = self.environment.from_string(source).render(
                    guest_enabled=enabled, utcnow=lambda: now,
                    states=lambda entity: "test-session" if entity.startswith("input_text") else mode,
                    state_attr=lambda entity, key: attrs.get(key),
                ).encode()
                data, _ = validate_presentation(raw, allowed, now.timestamp())
                self.assertEqual(data["enabled"], enabled)
                if not enabled:
                    self.assertEqual(data["hvac"], [])
                elif mode in {"unknown", "unavailable"}:
                    self.assertIsNone(data["hvac"][0]["current_temperature"])
                elif attrs.get("current_temperature") == 0:
                    self.assertEqual(data["hvac"][0]["current_temperature"], 0)

    def test_no_remote_commands_credentials_or_climate_mutations(self):
        actions = []
        def walk(value):
            if isinstance(value, dict):
                if "action" in value:
                    actions.append(value["action"])
                if value.get("action") == "mqtt.publish":
                    data = value["data"]
                    self.assertIn(data["topic"], {"porchlight/guest/presentation", "porchlight/guest/requested"})
                    if data["topic"].endswith("presentation"):
                        self.assertFalse(data["retain"])
                        self.assertNotIn("password", data["payload"])
                self.assertNotEqual(value.get("trigger"), "mqtt")
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(self.package)
        self.assertFalse(any(action.startswith(("climate.", "shell_command.", "rest_command.")) for action in actions))
        self.assertNotIn("media_player.turn_off", actions)
        self.assertIn("cast.show_lovelace_view", actions)
        self.assertFalse(self.package["input_boolean"]["porchlight_guest_mode_requested"]["initial"])
        self.assertFalse(self.package["input_boolean"]["porchlight_guest_ui_ready"]["initial"])
        self.assertNotIn("initial", self.package["input_boolean"]["porchlight_guest_mode_ready"])
        self.assertEqual(self.package["input_text"]["porchlight_guest_tv_status"]["initial"], "off")
