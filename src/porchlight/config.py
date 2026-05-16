from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path


DEFAULT_COMMON_PORTS = (
    22,
    53,
    80,
    81,
    139,
    443,
    445,
    548,
    554,
    631,
    1883,
    3000,
    3389,
    5000,
    5357,
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
)


@dataclass(frozen=True)
class Config:
    root: Path
    config_dir: Path
    state_dir: Path
    muster_state_dir: Path
    data_dir: Path
    www_dir: Path
    allowed_interfaces: tuple[str, ...]
    allowed_cidrs: tuple[str, ...]
    max_prefix: int
    private_only: bool
    scan_gateway: bool
    scan_tailscale: bool
    full_tcp_scan: bool
    version_probe: bool
    nse_scripts: bool
    udp_scan: bool
    common_ports: tuple[int, ...]
    nmap_host_timeout: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "porchlight.db"

    @property
    def events_path(self) -> Path:
        return self.data_dir / "events.ndjson"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def bool_value(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


def ports(value: str | None) -> tuple[int, ...]:
    if not value:
        return DEFAULT_COMMON_PORTS
    parsed = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        port = int(part)
        if port < 1 or port > 65535:
            raise ValueError(f"invalid port: {port}")
        parsed.append(port)
    return tuple(sorted(set(parsed)))


def load_config(apply: bool = False) -> Config:
    if apply:
        root = Path("/")
        config_dir = Path(os.environ.get("PORCHLIGHT_CONFIG_DIR", "/etc/porchlight"))
    else:
        root = Path(os.environ.get("PORCHLIGHT_MOCK_ROOT") or os.environ.get("MUSTER_MOCK_ROOT") or f"{os.environ.get('TMPDIR', '/tmp')}/porchlight-mock")
        config_dir = Path(os.environ.get("PORCHLIGHT_CONFIG_DIR", root / "etc/porchlight"))

    env = {}
    env.update(load_env_file(config_dir / "porchlight.env"))
    env.update(os.environ)

    def path(name: str, default: Path | str) -> Path:
        value = Path(env.get(name, str(default)))
        if apply:
            return value
        if value.is_absolute():
            try:
                value.relative_to(root)
                return value
            except ValueError:
                return root / value.relative_to("/")
        return root / value

    return Config(
        root=root,
        config_dir=config_dir,
        state_dir=path("PORCHLIGHT_STATE_DIR", "/run/porchlight" if apply else root / "run/porchlight"),
        muster_state_dir=path("MUSTER_STATE_DIR", "/run/muster" if apply else root / "run/muster"),
        data_dir=path("PORCHLIGHT_DATA_DIR", "/var/lib/porchlight" if apply else root / "var/lib/porchlight"),
        www_dir=path("PORCHLIGHT_WWW_DIR", "/var/lib/porchlight/www" if apply else root / "var/lib/porchlight/www"),
        allowed_interfaces=csv(env.get("PORCHLIGHT_ALLOWED_INTERFACES"), ("wlan0", "eth0")),
        allowed_cidrs=csv(env.get("PORCHLIGHT_ALLOWED_CIDRS"), ("auto",)),
        max_prefix=int(env.get("PORCHLIGHT_MAX_PREFIX", "24")),
        private_only=bool_value(env.get("PORCHLIGHT_PRIVATE_ONLY"), True),
        scan_gateway=bool_value(env.get("PORCHLIGHT_SCAN_GATEWAY"), True),
        scan_tailscale=bool_value(env.get("PORCHLIGHT_SCAN_TAILSCALE"), False),
        full_tcp_scan=bool_value(env.get("PORCHLIGHT_FULL_TCP_SCAN"), False),
        version_probe=bool_value(env.get("PORCHLIGHT_VERSION_PROBE"), True),
        nse_scripts=bool_value(env.get("PORCHLIGHT_NSE_SCRIPTS"), False),
        udp_scan=bool_value(env.get("PORCHLIGHT_UDP_SCAN"), False),
        common_ports=ports(env.get("PORCHLIGHT_COMMON_PORTS")),
        nmap_host_timeout=env.get("PORCHLIGHT_NMAP_HOST_TIMEOUT", "90s"),
    )


def validate_scan_network(cidr: str, config: Config) -> ipaddress.IPv4Network:
    network = ipaddress.ip_network(cidr, strict=False)
    if network.version != 4:
        raise ValueError(f"only IPv4 CIDRs are supported for active scan: {cidr}")
    if config.private_only and not network.is_private:
        raise ValueError(f"refusing non-private CIDR: {cidr}")
    if network.prefixlen < config.max_prefix:
        raise ValueError(f"refusing CIDR broader than /{config.max_prefix}: {cidr}")
    return network


def allowed_interface(name: str, config: Config) -> bool:
    return name in config.allowed_interfaces
