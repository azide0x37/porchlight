from __future__ import annotations

import ipaddress
import shutil
from .config import Config
from .discover import arp_scan_hosts, lan_hosts, network_context, tailscale_hosts
from .enrich import enrich_hosts_with_reverse_dns, enrich_services
from .identity import stable_key
from .nmap_xml import parse_nmap_xml
from .util import run_text


def merge_hosts(host_lists: list[list[dict]]) -> list[dict]:
    merged: dict[str, dict] = {}
    for host_list in host_lists:
        for host in host_list:
            key = host.get("ip")
            if not key:
                continue
            existing = merged.setdefault(key, {"ip": key, "sources": []})
            source = host.get("source")
            if source and source not in existing["sources"]:
                existing["sources"].append(source)
            for field, value in host.items():
                if field == "source":
                    continue
                if value not in (None, "", []):
                    existing[field] = value
            existing["active"] = bool(existing.get("active")) or bool(host.get("active"))
    for host in merged.values():
        host["stable_key"] = stable_key(host)
    return sorted(merged.values(), key=lambda item: ipaddress.ip_address(item["ip"]))


def active_scan_targets(context: dict, hosts: list[dict], config: Config, mode: str) -> list[str]:
    if mode == "discover":
        return []
    targets = []
    for host in hosts:
        ip = host.get("ip")
        if not host.get("active") or not ip:
            continue
        if ip.startswith("100.") and not config.scan_tailscale:
            continue
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if config.private_only and not address.is_private:
            continue
        targets.append(ip)
    if config.scan_gateway and context.get("gateway") not in {"unknown", None}:
        targets.append(context["gateway"])
    return sorted(set(targets), key=ipaddress.ip_address)


def run_nmap(targets: list[str], config: Config, mode: str) -> list[dict]:
    if not targets or not shutil.which("nmap"):
        return []
    port_arg = "-p-" if mode == "deep" and config.full_tcp_scan else "-p" + ",".join(str(port) for port in config.common_ports)
    command = [
        "nmap",
        "-sT",
        "-n",
        "--open",
        "--max-retries",
        "2",
        "--host-timeout",
        "10m" if mode == "deep" else config.nmap_host_timeout,
        port_arg,
        "-oX",
        "-",
        *targets,
    ]
    text = run_text(command, timeout=600 if mode == "deep" else 180)
    if not text:
        return []
    return parse_nmap_xml(text)


def collect_observations(config: Config, mode: str) -> tuple[dict, list[dict], list[dict], dict]:
    context = network_context(config)
    passive_hosts = [lan_hosts(config), tailscale_hosts()]
    if context.get("interface") not in {"unknown", None}:
        passive_hosts.append(arp_scan_hosts(context["interface"]))
    hosts = merge_hosts(passive_hosts)
    enrich_hosts_with_reverse_dns(hosts)

    targets = active_scan_targets(context, hosts, config, mode)
    services = run_nmap(targets, config, mode)
    enrich_services(services, config.http_title_timeout)
    meta = {
        "sources": {
            "lan_neighbor_count": len(passive_hosts[0]),
            "tailscale_count": len(passive_hosts[1]),
            "arp_scan_count": len(passive_hosts[2]) if len(passive_hosts) > 2 else 0,
            "nmap_service_count": len(services),
        },
        "scan_blocked": None,
        "targets_count": len(targets),
    }
    return context, hosts, services, meta
