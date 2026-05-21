from __future__ import annotations

from html import unescape
import re
import ssl
import urllib.error
import urllib.request

from .service_types import service_category, service_url
from .util import run_text


TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def clean_name(value: str) -> str:
    return value.strip().strip(".")


def reverse_dns_name(ip: str) -> str | None:
    text = run_text(["getent", "hosts", ip], timeout=3)
    if not text:
        return None
    parts = text.split()
    if len(parts) < 2:
        return None
    name = clean_name(parts[1])
    return name or None


def enrich_hosts_with_reverse_dns(hosts: list[dict]) -> None:
    for host in hosts:
        if host.get("hostname") or host.get("dns_name") or not host.get("ip"):
            continue
        name = reverse_dns_name(host["ip"])
        if name:
            host["reverse_dns"] = name


def http_title(url: str, timeout: float = 2.5) -> str | None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Porchlight/0.4", "Accept": "text/html,application/xhtml+xml"},
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type and "text/" not in content_type:
                return None
            raw = response.read(65536)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return None
    match = TITLE_RE.search(raw.decode("utf-8", errors="ignore"))
    if not match:
        return None
    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title[:120] if title else None


def enrich_services(services: list[dict], http_title_timeout: float = 2.5) -> None:
    for service in services:
        category = service_category(service)
        service["category"] = category
        url = service_url(service)
        if url:
            service["url"] = url
        if category == "http" and url and http_title_timeout > 0:
            title = http_title(url, timeout=http_title_timeout)
            if title:
                service["title"] = title
