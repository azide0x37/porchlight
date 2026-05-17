from __future__ import annotations

from pathlib import Path
import shutil
from .config import Config
from .store import Store
from .util import read_json, write_json

WEBROOT = Path(__file__).resolve().parent / "webroot"


def render(config: Config, store: Store) -> dict:
    config.www_dir.mkdir(parents=True, exist_ok=True)
    status = read_json(config.state_dir / "status.json")
    hosts = {"hosts": store.hosts()}
    services = {"services": store.services()}
    changes = {"recent_runs": store.recent_runs()}
    snapshot = {"status": status, "hosts": hosts["hosts"], "services": services["services"], "changes": changes}

    write_json(config.www_dir / "status.json", status)
    write_json(config.www_dir / "hosts.json", hosts)
    write_json(config.www_dir / "services.json", services)
    write_json(config.www_dir / "changes.json", changes)
    write_json(config.www_dir / "snapshot.json", snapshot)
    write_static(config.www_dir)
    return snapshot


def write_static(www_dir: Path) -> None:
    if not WEBROOT.is_dir():
        raise FileNotFoundError(f"missing dashboard webroot: {WEBROOT}")
    for source in WEBROOT.iterdir():
        destination = www_dir / source.name
        if source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
