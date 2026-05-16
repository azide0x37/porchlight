from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from .config import load_config


def main() -> int:
    config = load_config(apply=True)
    host = "0.0.0.0"
    port = 8765
    handler = partial(SimpleHTTPRequestHandler, directory=str(config.www_dir))
    server = ThreadingHTTPServer((host, port), handler)
    server.serve_forever()
    return 0
