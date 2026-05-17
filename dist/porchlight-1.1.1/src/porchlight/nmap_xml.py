from __future__ import annotations

import xml.etree.ElementTree as ET


def parse_nmap_xml(text: str) -> list[dict]:
    root = ET.fromstring(text)
    rows = []
    for host in root.findall("host"):
        addresses = {}
        for address in host.findall("address"):
            addr = address.get("addr")
            addrtype = address.get("addrtype")
            if addr and addrtype:
                addresses[addrtype] = addr
        ip = addresses.get("ipv4") or addresses.get("ipv6")
        if not ip:
            continue
        hostname = None
        hostname_node = host.find("hostnames/hostname")
        if hostname_node is not None:
            hostname = hostname_node.get("name")
        for port in host.findall("ports/port"):
            state_node = port.find("state")
            service_node = port.find("service")
            state = state_node.get("state") if state_node is not None else "unknown"
            service = {
                "ip": ip,
                "mac": addresses.get("mac"),
                "hostname": hostname,
                "proto": port.get("protocol", "tcp"),
                "port": int(port.get("portid", "0")),
                "state": state,
                "service_name": service_node.get("name") if service_node is not None else None,
                "product": service_node.get("product") if service_node is not None else None,
                "version": service_node.get("version") if service_node is not None else None,
                "source": "nmap",
            }
            rows.append(service)
    return rows
