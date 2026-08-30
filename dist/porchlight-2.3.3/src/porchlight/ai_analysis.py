from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config, bool_value
from .settings import DEFAULT_OPENAI, openai_settings
from .util import iso_age_seconds, now_iso, read_json


ANALYSIS_FINGERPRINT_VERSION = 2
MEANINGFUL_STATUS_FIELDS = (
    "network_cidr",
    "gateway",
    "hosts_seen",
    "active_hosts",
    "open_ports",
    "http_services",
    "rtsp_services",
    "mqtt_services",
    "internal_services",
)
HOST_FINGERPRINT_FIELDS = ("stable_key", "ip", "mac", "interface", "display_name", "status")
SERVICE_FINGERPRINT_FIELDS = (
    "ip",
    "proto",
    "port",
    "state",
    "service_name",
    "product",
    "version",
    "url",
    "title",
    "category",
)


ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["environment", "protocols", "hosts", "irregularities"],
    "properties": {
        "environment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["grade", "headline", "summary", "highlights", "concerns", "suggestions"],
            "properties": {
                "grade": {"type": "string", "enum": ["A", "B", "C", "D", "F"]},
                "headline": {"type": "string"},
                "summary": {"type": "string"},
                "highlights": {"type": "array", "items": {"type": "string"}},
                "concerns": {"type": "array", "items": {"type": "string"}},
                "suggestions": {"type": "array", "items": {"type": "string"}},
            },
        },
        "protocols": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "grade", "headline", "summary", "highlights", "concerns"],
                "properties": {
                    "name": {"type": "string"},
                    "grade": {"type": "string", "enum": ["A", "B", "C", "D", "F"]},
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                    "concerns": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "hosts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ip", "grade", "headline", "summary", "notes"],
                "properties": {
                    "ip": {"type": "string"},
                    "grade": {"type": "string", "enum": ["A", "B", "C", "D", "F"]},
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "irregularities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "title", "summary"],
                "properties": {
                    "severity": {"type": "string", "enum": ["info", "notice", "warning", "critical"]},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        },
    },
}


def run_ai_analysis(config: Config) -> dict[str, object]:
    settings = openai_settings(config.config_dir)
    model = settings.get("PORCHLIGHT_AI_MODEL") or DEFAULT_OPENAI["PORCHLIGHT_AI_MODEL"]
    service_tier = settings.get("PORCHLIGHT_AI_SERVICE_TIER") or DEFAULT_OPENAI["PORCHLIGHT_AI_SERVICE_TIER"]
    output_path = config.www_dir / "analysis.json"

    if not bool_value(settings.get("PORCHLIGHT_AI_ANALYSIS_ENABLE"), False):
        return write_status(output_path, "disabled", model, service_tier)
    api_key = settings.get("OPENAI_API_KEY", "")
    if not api_key:
        return write_status(output_path, "missing_key", model, service_tier)

    snapshot = read_json(config.www_dir / "snapshot.json")
    changes = read_json(config.www_dir / "changes.json")
    if not snapshot:
        return write_status(output_path, "missing_snapshot", model, service_tier)

    analysis_input = compact_analysis_input(snapshot, changes)
    snapshot_hash = meaningful_analysis_hash(snapshot, changes)
    existing = read_json(output_path)
    scan_age = iso_age_seconds(snapshot.get("status", {}).get("last_scan"))
    if scan_age is None or (config.scan_stale_seconds > 0 and scan_age > config.scan_stale_seconds):
        reason = "AI analysis skipped because the latest scan timestamp is missing or invalid."
        if scan_age is not None:
            reason = f"AI analysis skipped because the latest scan is stale ({int(scan_age)}s old)."
        return write_status(
            output_path,
            "stale_snapshot",
            model,
            service_tier,
            snapshot_hash=snapshot_hash,
            error=reason,
            stale_from=existing,
        )
    if (
        existing.get("status") == "ok"
        and existing.get("fingerprint_version") == ANALYSIS_FINGERPRINT_VERSION
        and existing.get("snapshot_hash") == snapshot_hash
        and existing.get("model") == model
        and existing.get("service_tier") == service_tier
    ):
        return {**existing, "cache_hit": True}

    write_status(output_path, "pending", model, service_tier, snapshot_hash=snapshot_hash, stale_from=existing)
    try:
        generated = request_analysis(api_key, model, service_tier, analysis_input)
        payload = normalize_generated_analysis(generated)
    except HTTPError as exc:
        return write_http_error_status(output_path, exc, model, service_tier, snapshot_hash, existing)
    except (URLError, TimeoutError, OSError) as exc:
        return write_status(
            output_path,
            "upstream_error",
            model,
            service_tier,
            snapshot_hash=snapshot_hash,
            error=describe_network_error(exc),
            stale_from=existing,
        )
    except ValueError as exc:
        return write_status(
            output_path,
            "invalid_response",
            model,
            service_tier,
            snapshot_hash=snapshot_hash,
            error=str(exc),
            stale_from=existing,
        )

    result = {
        "status": "ok",
        "source": "openai",
        "generated_at": now_iso(),
        "snapshot_hash": snapshot_hash,
        "fingerprint_version": ANALYSIS_FINGERPRINT_VERSION,
        "model": model,
        "service_tier": service_tier,
        "cache_hit": False,
        **payload,
    }
    atomic_write_json(output_path, result)
    return result


def compact_analysis_input(snapshot: dict, changes: dict) -> dict[str, object]:
    status = snapshot.get("status", {})
    hosts = snapshot.get("hosts", [])
    services = snapshot.get("services", [])
    irregularities = changes.get("irregularities", [])
    return {
        "status": status,
        "hosts": [
            {
                "ip": host.get("ip"),
                "stable_key": host.get("stable_key"),
                "mac": host.get("mac"),
                "display_name": host.get("display_name"),
                "status": host.get("status"),
                "names": host.get("names"),
            }
            for host in hosts[:160]
        ],
        "services": [
            {
                "display_name": service.get("display_name"),
                "ip": service.get("ip"),
                "proto": service.get("proto"),
                "port": service.get("port"),
                "state": service.get("state"),
                "service_name": service.get("service_name"),
                "product": service.get("product"),
                "version": service.get("version"),
                "title": service.get("title"),
                "category": service.get("category"),
            }
            for service in services[:260]
        ],
        "irregularities": irregularities[:60] if isinstance(irregularities, list) else [],
        "recent_runs": changes.get("recent_runs", [])[:8] if isinstance(changes.get("recent_runs"), list) else [],
    }


def stable_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def meaningful_analysis_hash(snapshot: dict[str, object], changes: dict[str, object]) -> str:
    status = snapshot.get("status") if isinstance(snapshot.get("status"), dict) else {}
    hosts = snapshot.get("hosts") if isinstance(snapshot.get("hosts"), list) else []
    services = snapshot.get("services") if isinstance(snapshot.get("services"), list) else []
    irregularities = changes.get("irregularities") if isinstance(changes.get("irregularities"), list) else []
    payload = {
        "fingerprint_version": ANALYSIS_FINGERPRINT_VERSION,
        "status": {field: status.get(field) for field in MEANINGFUL_STATUS_FIELDS},
        "hosts": canonical_records(hosts, HOST_FINGERPRINT_FIELDS, normalize_host_record),
        "services": canonical_records(services, SERVICE_FINGERPRINT_FIELDS),
        "irregularities": canonical_irregularities(irregularities),
    }
    return stable_hash(payload)


def canonical_records(
    records: list[object],
    fields: tuple[str, ...],
    normalizer=None,
) -> list[dict[str, object]]:
    canonical = []
    for record in records:
        if not isinstance(record, dict):
            continue
        item = {field: record.get(field) for field in fields}
        canonical.append(normalizer(item, record) if normalizer else item)
    return sorted(canonical, key=canonical_json)


def normalize_host_record(item: dict[str, object], record: dict[str, object]) -> dict[str, object]:
    names = record.get("names")
    if isinstance(names, str):
        normalized_names = sorted({name.strip() for name in names.split(",") if name.strip()})
    elif isinstance(names, list):
        normalized_names = sorted({str(name).strip() for name in names if str(name).strip()})
    else:
        normalized_names = []
    return {**item, "names": normalized_names}


def canonical_irregularities(irregularities: list[object]) -> list[dict[str, object]]:
    unique = {}
    for irregularity in irregularities:
        if not isinstance(irregularity, dict):
            continue
        item = {
            "kind": irregularity.get("kind"),
            "severity": irregularity.get("severity"),
            "subject_key": irregularity.get("subject_key"),
            "payload": irregularity.get("payload") if isinstance(irregularity.get("payload"), dict) else {},
        }
        unique[canonical_json(item)] = item
    return [unique[key] for key in sorted(unique)]


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def request_analysis(api_key: str, model: str, service_tier: str, analysis_input: dict[str, object]) -> dict[str, object]:
    request_payload = {
        "model": model,
        "service_tier": service_tier,
        "store": False,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are analyzing a private LAN appliance snapshot. "
                    "Use only the supplied JSON. Be concise, practical, and non-alarmist. "
                    "Treat generated advice as advisory and call out scan-to-scan irregularities."
                ),
            },
            {"role": "user", "content": json.dumps(analysis_input, sort_keys=True)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "porchlight_analysis",
                "strict": True,
                "schema": ANALYSIS_SCHEMA,
            }
        },
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    timeout = float(os.environ.get("PORCHLIGHT_AI_TIMEOUT_SECONDS", "90"))
    with urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    text = extract_response_text(body)
    if not text:
        raise ValueError("OpenAI response did not include output text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI response JSON must be an object")
    return parsed


def extract_response_text(body: dict[str, object]) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str):
        return output_text
    for item in body.get("output", []) if isinstance(body.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return content["text"]
    return ""


def normalize_generated_analysis(payload: dict[str, object]) -> dict[str, object]:
    for key in ("environment", "protocols", "hosts", "irregularities"):
        if key not in payload:
            raise ValueError(f"OpenAI response missing {key}")
    if not isinstance(payload["environment"], dict):
        raise ValueError("OpenAI environment analysis must be an object")
    if not isinstance(payload["protocols"], list) or not isinstance(payload["hosts"], list):
        raise ValueError("OpenAI protocol and host analyses must be arrays")
    if not isinstance(payload["irregularities"], list):
        raise ValueError("OpenAI irregularities must be an array")
    return {
        "environment": payload["environment"],
        "protocols": payload["protocols"],
        "hosts": payload["hosts"],
        "irregularities": payload["irregularities"],
    }


def write_http_error_status(
    path: Path,
    exc: HTTPError,
    model: str,
    service_tier: str,
    snapshot_hash: str,
    stale_from: dict[str, object],
) -> dict[str, object]:
    status = "rate_limited" if exc.code == 429 else "request_failed"
    if exc.code in {500, 502, 503, 504}:
        status = "upstream_error"
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    close = getattr(exc, "close", None)
    if callable(close):
        close()
    return write_status(
        path,
        status,
        model,
        service_tier,
        snapshot_hash=snapshot_hash,
        error=describe_http_error(exc),
        http_status=exc.code,
        retry_after=retry_after,
        stale_from=stale_from,
    )


def describe_http_error(exc: HTTPError) -> str:
    if exc.code == 429:
        return "OpenAI rate limit reached; Porchlight will retry on the next timer run."
    if exc.code == 401:
        return "OpenAI rejected the API key; check the key saved in Settings."
    if exc.code == 403:
        return "OpenAI rejected the request for this account or project."
    if exc.code in {500, 502, 503, 504}:
        return "OpenAI service is temporarily unavailable; Porchlight will retry on the next timer run."
    return f"OpenAI request failed with HTTP {exc.code}."


def describe_network_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "OpenAI request timed out; Porchlight will retry on the next timer run."
    if isinstance(exc, URLError):
        return f"OpenAI request could not be completed: {exc.reason}"
    return "OpenAI request could not be completed; Porchlight will retry on the next timer run."


def has_generated_analysis(payload: dict[str, object]) -> bool:
    return (
        isinstance(payload.get("environment"), dict)
        and isinstance(payload.get("protocols"), list)
        and isinstance(payload.get("hosts"), list)
        and isinstance(payload.get("irregularities"), list)
    )


def attach_stale_analysis(payload: dict[str, object], existing: dict[str, object]) -> None:
    if not has_generated_analysis(existing):
        return
    for key in ("source", "environment", "protocols", "hosts", "irregularities"):
        if key in existing:
            payload[key] = existing[key]
    payload["analysis_stale"] = True
    if existing.get("generated_at"):
        payload["last_success_at"] = existing["generated_at"]
    if existing.get("snapshot_hash"):
        payload["last_success_snapshot_hash"] = existing["snapshot_hash"]


def write_status(
    path: Path,
    status: str,
    model: str,
    service_tier: str,
    snapshot_hash: str | None = None,
    error: str | None = None,
    http_status: int | None = None,
    retry_after: str | None = None,
    stale_from: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "generated_at": now_iso(),
        "model": model,
        "service_tier": service_tier,
        "fingerprint_version": ANALYSIS_FINGERPRINT_VERSION,
    }
    if snapshot_hash:
        payload["snapshot_hash"] = snapshot_hash
    if error:
        payload["error"] = error
    if http_status:
        payload["http_status"] = http_status
    if retry_after:
        payload["retry_after"] = retry_after
    if stale_from:
        attach_stale_analysis(payload, stale_from)
    atomic_write_json(path, payload)
    return payload


def atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
