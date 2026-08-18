"""Local HTTP server for the CAD orbit viewer.

The Three.js page uses ES modules, which browsers will not load from
file://. Serve outputs/ on 127.0.0.1 so the viewer is just a URL.

Usage:
    .venv/bin/python -m solar_uav.cad_server
    then open http://127.0.0.1:8101/
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8101
ROOT = Path(__file__).resolve().parents[1] / "outputs"
VIEWER = "aircraft_viewer.html"


def url(path: str = "/") -> str:
    return f"http://{HOST}:{PORT}{path}"


def viewer_url() -> str:
    return url("/")


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        self._rewrite_index()
        return super().do_GET()

    def do_HEAD(self):
        self._rewrite_index()
        return super().do_HEAD()

    def _rewrite_index(self):
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html", ""):
            self.path = f"/{VIEWER}" + (f"?{query}" if query else "")

    def end_headers(self):
        if self.path.endswith(".html"):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def is_up(timeout_s: float = 0.4) -> bool:
    try:
        with urllib.request.urlopen(url(f"/{VIEWER}"), timeout=timeout_s) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def serve_forever(port: int = PORT) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, port), _Handler)
    print(f"CAD viewer  {viewer_url()}", flush=True)
    httpd.serve_forever()


def ensure_running(timeout_s: float = 4.0) -> str:
    """Start the server in a detached process if it is not already up."""
    if is_up():
        return viewer_url()
    try:
        probe = socket.socket()
        probe.bind((HOST, PORT))
        probe.close()
    except OSError as exc:
        raise RuntimeError(
            f"port {PORT} is busy but the CAD viewer is not answering"
        ) from exc
    subprocess.Popen(
        [sys.executable, "-m", "solar_uav.cad_server"],
        cwd=str(ROOT.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_up():
            return viewer_url()
        time.sleep(0.05)
    raise RuntimeError(f"CAD server did not start on {viewer_url()}")


def main() -> None:
    serve_forever()


if __name__ == "__main__":
    main()
