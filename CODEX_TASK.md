# Codex Task

Maintain Porchlight as a Muster self-certified Linux service appliance.

Current scope:

- Keep the Home Assistant MQTT bridge mock-first and fail-closed.
- Preserve the single Home Assistant device model for the Porchlight scanner appliance.
- Keep scanner detail in Porchlight's own dashboard and state ledger.
- Do not mark the project complete unless `make test` and `make package` pass.

When adding scanner services, feed the existing state surfaces first:

- `/run/porchlight/status.json`
- `/run/muster/status.json`
- `/var/lib/porchlight/www/*.json`

Cross-agent notes:

- Before continuing guest-mode work, read
  `docs/workstreams/notes/2026-10-17-guest-screen-handoff-to-codex.md` (asks from
  the guest TV screen: HA HVAC payload fixtures, display adapter, docs alignment).
