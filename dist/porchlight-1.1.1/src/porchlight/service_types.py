from __future__ import annotations


HTTP_PORTS = {80, 81, 443, 5000, 5357, 8000, 8008, 8080, 8081, 8123, 8443, 9000}
RTSP_PORTS = {554, 8554}
MQTT_PORTS = {1883, 8883}
INTERNAL_PORTS = {
    22,
    53,
    139,
    445,
    548,
    631,
    3000,
    3389,
    5900,
    8000,
    8008,
    8080,
    8081,
    8123,
    8443,
    9000,
    9100,
    32400,
}


def service_category(service: dict) -> str:
    port = int(service.get("port") or 0)
    name = str(service.get("service_name") or "").lower()
    product = str(service.get("product") or "").lower()
    text = f"{name} {product}"
    if port in MQTT_PORTS or "mqtt" in text:
        return "mqtt"
    if port in RTSP_PORTS or "rtsp" in text:
        return "rtsp"
    if port in HTTP_PORTS or "http" in text:
        return "http"
    if port in INTERNAL_PORTS:
        return "internal"
    return "other"


def service_counts(services: list[dict]) -> dict[str, int]:
    counts = {
        "http_services": 0,
        "rtsp_services": 0,
        "mqtt_services": 0,
        "internal_services": 0,
    }
    for service in services:
        category = service.get("category") or service_category(service)
        if category == "http":
            counts["http_services"] += 1
        elif category == "rtsp":
            counts["rtsp_services"] += 1
        elif category == "mqtt":
            counts["mqtt_services"] += 1
        elif category == "internal":
            counts["internal_services"] += 1
    return counts


def service_url(service: dict) -> str | None:
    category = service.get("category") or service_category(service)
    if category not in {"http", "rtsp"}:
        return None
    ip = service.get("ip")
    port = int(service.get("port") or 0)
    if not ip or port <= 0:
        return None
    name = str(service.get("service_name") or "").lower()
    product = str(service.get("product") or "").lower()
    text = f"{name} {product}"
    if category == "rtsp":
        return f"rtsp://{ip}:{port}/"
    scheme = "https" if port in {443, 8443} or "ssl" in text or "https" in text else "http"
    default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    suffix = "" if default else f":{port}"
    return f"{scheme}://{ip}{suffix}/"
