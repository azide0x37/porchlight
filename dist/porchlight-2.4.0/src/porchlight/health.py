from __future__ import annotations

from datetime import datetime, timezone
from .config import Config
from .util import iso_age_seconds, read_json, write_json


def scan_status_problems(
    status: dict,
    stale_after_seconds: int,
    current_time: datetime | None = None,
) -> tuple[list[str], float | None]:
    last_scan = status.get("last_scan")
    if not last_scan:
        return ["scan status missing"], None
    age = iso_age_seconds(last_scan, current_time)
    if age is None:
        return ["scan timestamp invalid"], None
    if stale_after_seconds > 0 and age > stale_after_seconds:
        return [f"scan status stale ({int(age)}s old)"], age
    return [], age


def health(config: Config, current_time: datetime | None = None) -> dict:
    problems = []
    status = read_json(config.state_dir / "status.json")
    if not config.db_path.exists():
        problems.append("database missing")
    if not (config.www_dir / "snapshot.json").exists():
        problems.append("dashboard snapshot missing")
    scan_problems, scan_age = scan_status_problems(status, config.scan_stale_seconds, current_time)
    problems.extend(scan_problems)

    health_state = "healthy" if not problems else "degraded"
    payload = {
        "health": health_state,
        "degraded": bool(problems),
        "scanner_online": health_state == "healthy",
        "problems": problems,
        "last_scan": status.get("last_scan"),
        "scan_age_seconds": round(scan_age, 1) if scan_age is not None else None,
        "updated_at": (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_json(config.muster_state_dir / "status.json", payload)
    return payload
