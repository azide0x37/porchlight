from __future__ import annotations


def stable_key(host: dict) -> str:
    mac = host.get("mac")
    if mac:
        return f"mac:{str(mac).lower()}"
    tailscale_ips = host.get("tailscale_ips") or []
    if tailscale_ips:
        return f"tailscale:{tailscale_ips[0]}"
    dns_name = host.get("dns_name")
    if dns_name:
        return f"dns:{str(dns_name).lower().rstrip('.')}"
    hostname = host.get("hostname")
    if hostname and hostname != "unknown":
        return f"name:{str(hostname).lower()}"
    return f"ip:{host['ip']}"


def display_name(host: dict) -> str:
    return host.get("hostname") or host.get("dns_name") or host.get("ip")
