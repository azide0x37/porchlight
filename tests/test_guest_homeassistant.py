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


FIXTURE_TIME = datetime(2026, 10, 17, 18, tzinfo=timezone.utc)
ZONE_IDS = ("climate.living_room_thermostat", "climate.bedroom_ac", "climate.kitchen_ac")


def fixture_cases():
    """Synthetic inputs to the actual HA template; no thermostat is changed."""
    single_zone_cases = {
        "heat": ("heat", {"temperature": 70, "current_temperature": 68.5, "hvac_action": "heating"}),
        "cool": ("cool", {"temperature": 72, "current_temperature": 73.25, "hvac_action": "cooling"}),
        # Some integrations retain both single and range attributes. Preserve both.
        "heat_cool": ("heat_cool", {"temperature": 71, "target_temp_low": 68,
                                      "target_temp_high": 74, "hvac_action": "idle"}),
        "off": ("off", {"current_temperature": 0, "hvac_action": "off"}),
        "fan_only": ("fan_only", {"current_temperature": 73, "hvac_action": "fan"}),
        "dry": ("dry", {"current_temperature": 73, "hvac_action": "drying"}),
        "unavailable": ("unavailable", {"current_temperature": 99, "temperature": 66}),
        "unknown": ("unknown", {}),
        "celsius": ("heat", {"temperature": 21.5, "current_temperature": 20.5, "hvac_action": "heating"}),
    }
    cases = {
        name: (True, {entity: value for entity in ZONE_IDS}, "°C" if name == "celsius" else "°F")
        for name, value in single_zone_cases.items()
    }
    cases["mixed_zones"] = (True, dict(zip(ZONE_IDS, (
        single_zone_cases["heat"], single_zone_cases["cool"], single_zone_cases["unavailable"],
    ))), "°F")
    cases["disabled"] = (False, {entity: single_zone_cases["cool"] for entity in ZONE_IDS}, "°F")
    return cases


def render_fixture(environment, source, enabled, zones, unit):
    # The live tenant is Fahrenheit. This explicit test-only variant documents
    # the same template's receiver contract for a Celsius deployment.
    if unit == "°C":
        assert source.count("'unit': '°F'") == 1
        source = source.replace("'unit': '°F'", "'unit': '°C'")
    return json.loads(environment.from_string(source).render(
        guest_enabled=enabled, utcnow=lambda: FIXTURE_TIME,
        states=lambda entity: "fixture-session" if entity.startswith("input_text") else zones[entity][0],
        state_attr=lambda entity, key: zones[entity][1].get(key),
        integration_entities=lambda _: [],
    ))


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
        for name, (enabled, zones, unit) in fixture_cases().items():
            with self.subTest(case=name):
                rendered = render_fixture(self.environment, source, enabled, zones, unit)
                expected = json.loads((ROOT / f"examples/guest-mode/fixtures/presentation.{name}.json").read_text())
                self.assertEqual(rendered, expected)
                data, _ = validate_presentation(json.dumps(rendered).encode(), set(ZONE_IDS), FIXTURE_TIME.timestamp())
                self.assertEqual(data["enabled"], enabled)
                if not enabled:
                    self.assertEqual(data["hvac"], [])
                else:
                    self.assertEqual(len(data["hvac"]), 3)
                    self.assertEqual([zone["label"] for zone in data["hvac"]], ["Living room", "Bedroom", "Kitchen"])
                    for zone in data["hvac"]:
                        mode, attrs = zones[zone["id"]]
                        self.assertEqual(zone["unit"], unit)
                        self.assertEqual(zone["mode"], mode if zone["available"] else None)
                        self.assertEqual(zone["current_temperature"], attrs.get("current_temperature") if zone["available"] else None)

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
        self.assertNotIn("initial", self.package["input_boolean"]["porchlight_guest_ui_ready"])
        self.assertNotIn("initial", self.package["input_boolean"]["porchlight_guest_mode_ready"])
        for helper in ("porchlight_guest_dashboard_path", "porchlight_guest_view_path"):
            self.assertNotIn("initial", self.package["input_text"][helper])
        self.assertEqual(self.package["input_text"]["porchlight_guest_tv_status"]["initial"], "off")

    def test_display_adapter_cannot_bypass_commissioning_or_change_service(self):
        sequence = self.package["script"]["porchlight_guest_present_on_tv"]["sequence"]
        guard = next(step["if"] for step in sequence if "porchlight_guest_ui_ready" in step.get("if", ""))
        for ready, adapter, dashboard, view, blocked in [
            (False, True, "", "", True),
            (False, False, "guest-screen", "guest", True),
            (True, False, "", "guest", True),
            (True, False, "https://example.test/", "guest", True),
            (True, False, "guest-screen", "../settings", True),
            (True, False, "guest-screen", "guest", False),
            (True, True, "", "", False),
        ]:
            with self.subTest(ready=ready, adapter=adapter, dashboard=dashboard, view=view):
                rendered = self.environment.from_string(guard).render(
                    is_state=lambda entity, state: ready,
                    states=lambda entity: dashboard if entity.endswith("dashboard_path") else view,
                    has_service=lambda domain, service: adapter and (domain, service) == ("script", "porchlight_guest_open_display"),
                )
                self.assertEqual(rendered.strip(), str(blocked))
        dispatch = next(step for step in sequence if "choose" in step)
        self.assertEqual(dispatch["choose"][0]["sequence"][0]["action"], "script.porchlight_guest_open_display")
        self.assertEqual(dispatch["default"][0]["action"], "cast.show_lovelace_view")

    def test_spotify_auto_selects_playing_before_paused_without_art_tokens(self):
        source = self.package["script"]["porchlight_guest_publish"]["sequence"][1]["data"]["payload"]
        zones = fixture_cases()["cool"][1]
        for entity, state in (("media_player.a_spotify", "paused"), ("media_player.z_spotify", "playing")):
            zones[entity] = (state, {"media_title": "Test track", "media_artist": "Test artist",
                                    "media_duration": 240, "media_position": 30,
                                    "entity_picture": "/secret?token=never-export"})
        data = json.loads(self.environment.from_string(source).render(
            guest_enabled=True, utcnow=lambda: FIXTURE_TIME,
            states=lambda e: "fixture-session" if e.startswith("input_text") else zones[e][0],
            state_attr=lambda e, key: zones[e][1].get(key),
            integration_entities=lambda _: ["media_player.a_spotify", "media_player.z_spotify"],
        ))
        self.assertEqual(data["spotify"]["id"], "media_player.z_spotify")
        self.assertNotIn("never-export", json.dumps(data))
        validate_presentation(json.dumps(data).encode(), set(ZONE_IDS), FIXTURE_TIME.timestamp(), [data["spotify"]["id"]])
