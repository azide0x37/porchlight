from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from .config import load_config


class PorchlightHTTPRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.endswith((".html", ".css", ".js", ".json", ".webmanifest")) or path == "/":
            self.send_header("Cache-Control", "no-store")
        elif path.endswith((".png", ".svg", ".woff2")):
            self.send_header("Cache-Control", "public, max-age=604800")
        super().end_headers()


def main() -> int:
    config = load_config(apply=True)
    host = "0.0.0.0"
    port = 8765
    handler = partial(PorchlightHTTPRequestHandler, directory=str(config.www_dir))
    server = ThreadingHTTPServer((host, port), handler)
    server.serve_forever()
    return 0
