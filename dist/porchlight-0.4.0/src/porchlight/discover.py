from __future__ import annotations

import ipaddress
from .config import Config, allowed_interface
from .util import run_json, run_text


def primary_tailscale_ip(peer: dict) -> str | None:
    for ip in peer.get("TailscaleIPs") or []:
        if isinstance(ip, str) and ip.startswith("100."):
            return ip
    ips = peer.get("TailscaleIPs") or []
    return ips[0] if ips else None


def network_context(config: Config) -> dict:
    routes = run_json(["ip", "-j", "route", "show", "default"]) or []
    addrs = run_json(["ip", "-j", "addr", "show"]) or []
    route = next((row for row in routes if allowed_interface(row.get("dev", ""), config)), routes[0] if routes else {})
    interface = route.get("dev")
    gateway = route.get("gateway", "unknown")
    cidr = "unknown"

    for iface in addrs:
        if iface.get("ifname") != interface:
            continue
        for addr in iface.get("addr_info", []):
            if addr.get("family") != "inet":
                continue
            local = addr.get("local")
            prefix = addr.get("prefixlen")
            if local and prefix is not None:
                cidr = str(ipaddress.ip_network(f"{local}/{prefix}", strict=False))
                break
    return {"interface": interface or "unknown", "gateway": gateway, "network_cidr": cidr}


def lan_hosts(config: Config) -> list[dict]:
    rows = run_json(["ip", "-j", "neigh", "show"]) or []
    hosts = []
    for row in rows:
        ip = row.get("dst")
        interface = row.get("dev")
        states = row.get("state") or []
        if not ip or ":" in ip or not allowed_interface(interface or "", config):
            continue
        state = states[0] if states else "UNKNOWN"
        active = state not in {"FAILED", "INCOMPLETE"} and bool(row.get("lladdr"))
        hosts.append(
            {
                "ip": ip,
                "mac": row.get("lladdr"),
                "interface": interface,
                "state": state,
                "active": active,
                "source": "lan-neighbor",
            }
        )
    return hosts


def parse_arp_scan(text: str) -> list[dict]:
    hosts = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Interface:") or line.startswith("Starting ") or line.startswith("Ending "):
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            ipaddress.ip_address(parts[0])
        except ValueError:
            continue
        host = {"ip": parts[0], "mac": parts[1].lower(), "active": True, "source": "arp-scan"}
        if len(parts) > 2:
            host["vendor"] = parts[2]
        hosts.append(host)
    return hosts


def arp_scan_hosts(interface: str) -> list[dict]:
    text = run_text(["arp-scan", "--localnet", f"--interface={interface}"], timeout=45)
    if not text:
        return []
    return parse_arp_scan(text)


def tailscale_hosts() -> list[dict]:
    status = run_json(["tailscale", "status", "--json"])
    if not isinstance(status, dict):
        return []

    hosts = []
    self_peer = status.get("Self")
    if isinstance(self_peer, dict):
        hosts.append(tailscale_host(self_peer, self_node=True))

    peers = status.get("Peer") or {}
    for peer in peers.values():
        if isinstance(peer, dict):
            hosts.append(tailscale_host(peer, self_node=False))
    return [host for host in hosts if host.get("ip")]


def tailscale_host(peer: dict, self_node: bool) -> dict:
    dns_name = peer.get("DNSName") or ""
    name = peer.get("HostName") or dns_name.rstrip(".") or "unknown"
    return {
        "ip": primary_tailscale_ip(peer),
        "tailscale_ips": peer.get("TailscaleIPs") or [],
        "hostname": name,
        "dns_name": dns_name.rstrip("."),
        "os": peer.get("OS"),
        "online": bool(peer.get("Online")),
        "active": bool(peer.get("Online")),
        "self": self_node,
        "last_seen": peer.get("LastSeen"),
        "source": "tailscale",
    }
