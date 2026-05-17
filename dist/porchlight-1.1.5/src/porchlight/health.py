from __future__ import annotations

from datetime import datetime, timezone
from .config import Config
from .util import read_json, write_json


def health(config: Config) -> dict:
    problems = []
    status = read_json(config.state_dir / "status.json")
    if not config.db_path.exists():
        problems.append("database missing")
    if not (config.www_dir / "snapshot.json").exists():
        problems.append("dashboard snapshot missing")
    if not status.get("last_scan"):
        problems.append("scan status missing")

    health_state = "healthy" if not problems else "degraded"
    payload = {
        "health": health_state,
        "degraded": bool(problems),
        "scanner_online": health_state == "healthy",
        "problems": problems,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_json(config.muster_state_dir / "status.json", payload)
    return payload
