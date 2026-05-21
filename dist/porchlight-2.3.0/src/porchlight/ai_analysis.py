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
from .util import now_iso, read_json


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
    snapshot_hash = stable_hash(analysis_input)
    existing = read_json(output_path)
    if existing.get("status") == "ok" and existing.get("snapshot_hash") == snapshot_hash:
        return existing

    write_status(output_path, "pending", model, service_tier, snapshot_hash=snapshot_hash)
    try:
        generated = request_analysis(api_key, model, service_tier, analysis_input)
        payload = normalize_generated_analysis(generated)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return write_status(output_path, "error", model, service_tier, snapshot_hash=snapshot_hash, error=str(exc))

    result = {
        "status": "ok",
        "source": "openai",
        "generated_at": now_iso(),
        "snapshot_hash": snapshot_hash,
        "model": model,
        "service_tier": service_tier,
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


def write_status(
    path: Path,
    status: str,
    model: str,
    service_tier: str,
    snapshot_hash: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "generated_at": now_iso(),
        "model": model,
        "service_tier": service_tier,
    }
    if snapshot_hash:
        payload["snapshot_hash"] = snapshot_hash
    if error:
        payload["error"] = error
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
