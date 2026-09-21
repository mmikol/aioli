"""The board: the one page, and the health the container is judged by.

A thin router over http.server. The handler routes and renders; what it
renders comes from the kitchen, the planner and the matching layer, and
nothing here reaches into the database on its own.

The board binds to 127.0.0.1 in the container and nothing is published.
`tailscale serve` on the host is what carries a phone to it, so a
confirmation is a tap at the moment the answer is known (docs/fleet.md).
"""
import argparse
import json
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from db import psql

STATIC = pathlib.Path(__file__).parent / "static"

# Served as-is, and nothing else is: a path that is not on this map does not
# reach the filesystem.
STATIC_FILES = {
    "/static/board.css": "text/css; charset=utf-8",
    "/static/board.js": "application/javascript; charset=utf-8",
}


def health():
    """What the container's healthcheck asks: is the schema where we left it.

    A migration still pending means the image and the database disagree. That
    is a failure even though every query would still answer.
    """
    with psql.connect() as cx:
        outstanding = [path.name for _, path in psql.pending(cx)]
        tables = cx.execute(
            "select count(*) as n from information_schema.tables"
            " where table_schema = 'public'").fetchone()["n"]
    return {"status": "ok" if not outstanding else "migrations pending",
            "pending": outstanding,
            "tables": tables}


class Handler(BaseHTTPRequestHandler):
    """Routing, and the errors a browser should see rather than a stack."""

    # A connection that opens and sends nothing otherwise blocks in readline
    # with no deadline, and ThreadingHTTPServer gives every connection its own
    # thread and no cap. The board answers from the tailnet and has no login of
    # its own, so a stalled socket must not be able to hold a thread for good.
    timeout = 10

    def log_message(self, fmt, *args):     # the default logs to stderr per hit
        pass

    def _send(self, code, body, kind="text/html; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, body, code=200):
        self._send(code, json.dumps(body, default=str), "application/json")

    def do_GET(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        try:
            if path == "/health":
                # A pending migration has to reach the healthcheck as a status
                # code: the checker calls urlopen and looks at nothing else, so
                # a failure written only into the body is a failure nobody
                # reads. 503 is the honest one - up, and not fit to serve.
                body = health()
                return self._json(body, 200 if body["status"] == "ok" else 503)
            if path in STATIC_FILES:
                found = STATIC / pathlib.Path(path).name
                if not found.exists():
                    return self._send(404, "not found", "text/plain")
                return self._send(200, found.read_bytes(), STATIC_FILES[path])
            return self._route(path, query)
        except Exception as bad:           # a stack trace is not a page
            return self._send(500, "the board failed: %s" % bad, "text/plain")

    def _route(self, path, query):
        """The pages. Filled as the modules beneath them land."""
        if path == "/":
            return self._send(200, page())
        return self._send(404, "no such page", "text/plain")


def page():
    """The shell every view is rendered into."""
    return ("<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<link rel='stylesheet' href='/static/board.css'>"
            "<title>AIoli</title>"
            "<main><h1>AIoli</h1>"
            "<p class='quiet'>the kitchen is wired; the week is not planned yet.</p>"
            "</main>")


def main(argv=None):
    ap = argparse.ArgumentParser(description="the board")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8018)
    args = ap.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("the board is on http://%s:%d" % (args.host, args.port), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
