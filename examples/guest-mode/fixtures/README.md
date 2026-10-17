# Guest presentation fixtures

These are **synthetic scenarios rendered by the committed Home Assistant MQTT
template**, not recordings of thermostat changes. `tests/test_guest_homeassistant.py`
compares every JSON file with that template and validates it with the production
receiver. The fixed timestamp is intentional; these files must not be published
as live snapshots.

Cases cover heat, cool, heat/cool range, off, fan-only, dry, unknown, unavailable,
mixed zones, a Celsius deployment, and guest mode disabled. Each enabled snapshot
has the tenant's three explicitly allowlisted zones. The Celsius case changes the
template's fixed unit to °C **only in the test**; this household's package emits °F.

- Labels come from the package's explicit entity/label mapping, not friendly names.
- The unit is configured in the package; it is not inferred from individual entities.
- Numeric attributes pass through `float(none)` without rounding. The cool fixture
  includes 73.25 to make this visible; screen rounding is a presentation decision.
- Single and range targets can coexist when the integration supplies both. The
  `heat_cool` fixture deliberately exercises that case; display the range in that mode.
- Unknown/unavailable zones retain their label and ID, with temperature, mode, and
  action fields null. Guest mode disabled emits an empty HVAC list.
- The receiver allows at most eight zones; this deployed package emits three.
