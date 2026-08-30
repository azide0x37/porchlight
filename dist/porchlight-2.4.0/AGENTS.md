# Agent Instructions

- Pull latest before action when the working tree is clean enough to do so.
- Use `uv` for Python commands.
- Do not declare this repo Muster-complete unless `make test` and `make package` pass, or failures are documented with exact output.
- Keep Home Assistant MQTT controls allowlisted and fail closed.
- Preserve `/etc/porchlight` config across install, update, and uninstall unless `--purge` is explicitly requested.
- Update the README self-certification table whenever lifecycle behavior, tests, packaging, or Muster pattern mapping changes.
