"""Serve the split-empennage Three.js viewer over HTTP.

Usage:
  .venv/bin/python split_empennage/scripts/serve_viewer.py
  .venv/bin/python split_empennage/scripts/serve_viewer.py --port 8765
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "outputs"
DEFAULT_PORT = 8765


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = p.parse_args()
    html = ROOT / "aircraft_viewer.html"
    if not html.exists():
        sys.exit(f"Missing {html}. Run split_empennage/scripts/visualize.py first.")

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/aircraft_viewer.html"
        print(f"Serving {ROOT}", flush=True)
        print(url, flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
