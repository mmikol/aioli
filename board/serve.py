"""The board: the pages, and the health the container is judged by.

A thin router over http.server. The handler routes and renders; what it
renders comes from the kitchen, the planner and the matching layer, and no
statement in this file is addressed to a table. The two things it opens a
connection for itself are the healthcheck and the purge at boot, and both ask
their question through the module that owns it - db/psql.py and
planner/week.py.

The board is reachable on the host's loopback and nowhere else: compose
publishes it as 127.0.0.1:8018, and inside the container it binds 0.0.0.0
because a bind to the container's own loopback is a published port nothing
can reach. `tailscale serve` on the host is what carries a phone to it, so a
confirmation is a tap at the moment the answer is known (docs/fleet.md).
"""
import argparse
import json
import pathlib
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from board import pages, plan_pages
from db import psql
from planner import groceries, week

STATIC = pathlib.Path(__file__).parent / "static"

# The pages, from the modules that render them. The week comes first so that
# "/" is the week.
ROUTES = plan_pages.ROUTES + pages.ROUTES

# The same table, keyed the way a request arrives. Built once at import: the
# routes are a property of the modules, not of a request.
RENDERS = {(route.path, route.method): route.render for route in ROUTES}
PATHS = frozenset(route.path for route in ROUTES)

# A form from this board is a few hundred bytes. Anything larger is not one,
# and reading it would be reading whatever was sent.
MOST_FORM_BYTES = 64 * 1024

# What a browser says about where a request came from. A request with no such
# header is one from something that is not a modern browser, and 'none' is a
# person typing the address; neither is the cross-site request `_elsewhere`
# refuses.
OWN_SITE = ("same-origin", "none")

# Served as-is, and nothing else is: a path that is not on this map does not
# reach the filesystem.
STATIC_FILES = {
    "/static/board.css": "text/css; charset=utf-8",
    "/static/board.js": "application/javascript; charset=utf-8",
}


def health() -> dict[str, object]:
    """What the container's healthcheck asks: is the schema where we left it.

    A migration still pending means the image and the database disagree. That
    is a failure even though every query would still answer.
    """
    with psql.connect() as cx:
        outstanding = [path.name for _, path in psql.pending(cx)]
        held = psql.tables(cx)
    return {"status": "ok" if not outstanding else "migrations pending",
            "pending": outstanding,
            "tables": held}


def purge_passed_plans(cx=None) -> int:
    """Close the weeks that are over and purge their recipe pointers.

    Done as the board starts. A pointer is the one thing the service touched
    that reaches a table at all, and docs/db.md promises it goes when the
    period closes; the scheduler that would keep that promise on a clock is an
    item after the MVP (pm/backlog.md). So the two things that do happen carry
    it: a week being planned, and this process starting. The board runs for
    weeks at a time and starts rarely, which is exactly why the planner does
    it as well.

    A connection handed in is the caller's to commit, as every render here is;
    opened here, it is committed here, because nothing else will.
    """
    if cx is not None:
        return week.close_passed(cx)
    with psql.connect() as own:
        purged = week.close_passed(own)
        own.commit()
        return purged


class Handler(BaseHTTPRequestHandler):
    """Routing, and the errors a browser should see rather than a stack."""

    # A connection that opens and sends nothing otherwise blocks in readline
    # with no deadline, and ThreadingHTTPServer gives every connection its own
    # thread and no cap. The board answers from the tailnet and has no login of
    # its own, so a stalled socket must not be able to hold a thread for good.
    timeout = 10

    def log_message(self, fmt: str, *args) -> None:     # the default logs to stderr per hit
        pass

    def _send(self, code: int, body: bytes | str,
              kind: str = "text/html; charset=utf-8") -> None:
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, body: object, code: int = 200) -> None:
        self._send(code, json.dumps(body, default=str), "application/json")

    def _elsewhere(self) -> bool:
        """Whether this request came from a page on some other site.

        The board has no login and no token to check, so what stops a page
        elsewhere binning a pantry row - or spending a day's recipe quota
        through `/groceries`, which is a GET that costs money - is the
        browser's own word for where the request came from.

        A top-level navigation is refused along with the rest, deliberately.
        Exempting one would let a page elsewhere send a browser to
        `/groceries`, and the only thing it would buy is a link in the midweek
        mail, which nobody has built (pm/backlog.md). A board opened from a
        bookmark or typed in says 'none' and is let through.
        """
        site = self.headers.get("Sec-Fetch-Site")
        return site is not None and site not in OWN_SITE

    def _failed(self) -> None:
        """What a browser is told, and what the container's log is told.

        The traceback goes to stderr, where `docker logs` finds it, and not
        into the page: an exception's own text here can carry a connection
        string, and a person reading a 500 on a phone can do nothing with a
        stack anyway.
        """
        traceback.print_exc()
        return self._send(500, "the board failed", "text/plain")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if self._elsewhere():
            return self._send(403, "this board is read from this board", "text/plain")
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
        except Exception:                  # a stack trace is not a page
            return self._failed()

    def do_POST(self) -> None:
        """A form on the board: an edit to the pantry, the settings or a meal.

        Every write is a POST that renders the page it wrote to, so a phone
        that answered a confirmation sees the answer land rather than a blank
        response it has to navigate away from.

        A post from somewhere else is refused before anything is routed, the
        way a read from somewhere else is: see `_elsewhere`.
        """
        path = urlparse(self.path).path
        if self._elsewhere():
            return self._send(403, "a form on this board is posted from this board",
                              "text/plain")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, "a form wants a length", "text/plain")
        if length > MOST_FORM_BYTES:
            return self._send(413, "that is more than a form should be", "text/plain")
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        try:
            return self._route(path, parse_qs(body), method="POST")
        except Exception:
            return self._failed()

    def _route(self, path: str, query: dict, method: str = "GET") -> None:
        """The pages, from the route tables the modules beneath publish.

        A connection per request, and the connection is the transaction: the
        render writes and returns, and the `with` commits on a clean return or
        rolls back when the render raises. That is why a view that wants a
        write undone raises rather than handing back a page. One household with
        one reader, so nothing here pools.
        """
        render = RENDERS.get((path, method))
        if render is None:
            if path in PATHS:
                return self._send(405, "that page does not take a %s" % method, "text/plain")
            return self._send(404, "no such page", "text/plain")
        with psql.connect() as cx:
            return self._send(200, render(cx, query))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the board")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8018)
    args = ap.parse_args(argv)
    # The purge is worth doing and not worth dying for. A board against a
    # database nobody has migrated should come up and say so through /health,
    # which is the tolerance every view here already implements; a process
    # that fell over before binding would answer nothing at all.
    try:
        purged = purge_passed_plans()
    except Exception as bad:               # noqa: BLE001 - said, then carried on
        print("the weeks that are over could not be closed: %s" % bad, flush=True)
        purged = 0
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("the board is on http://%s:%d" % (args.host, args.port), flush=True)
    if purged:
        print("%d recipe pointer(s) purged from weeks that are over" % purged, flush=True)
    try:
        server.serve_forever()
    finally:
        # The terms say everything obtained goes when the key does, and a
        # process on its way out is the same promise (docs/db.md). Both holds
        # are daemon threads and would die with it anyway; saying so is the
        # promise kept rather than left to the runtime.
        pages.STOVE.stop()
        groceries.HELD.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
