"""The router: that every page the modules publish is reachable, that the
healthcheck says what the container needs to hear, that nothing but the two
static files reaches the filesystem, and that a failure is a sentence rather
than a stack.

No socket and no port. BaseHTTPRequestHandler reads a request off `rfile` and
writes its answer to `wfile`, so the board can be asked a question here
without anything being listened on - which is also why this file can run
beside the rest of the suite without a port to collide over.
"""
import io
import pathlib

import pytest

from board import chrome, pages, plan_pages, serve
from db import psql


class Borrowed:
    """The test's own connection, lent to a render and never committed.

    The handler opens a connection per request, and the suite's connection is
    a temporary schema inside a transaction that is thrown away. So `connect`
    is replaced by one that hands the same connection over and leaves the
    committing to nobody.
    """

    def __init__(self, cx):
        self.cx = cx

    def __call__(self, *anything, **rest):
        return self

    def __enter__(self):
        return self.cx

    def __exit__(self, *bad):
        return False


def lent(monkeypatch, db):
    """Every connection the board opens is the one this test is holding."""
    monkeypatch.setattr(psql, "connect", Borrowed(db))


def asked(request):
    """One request driven through the handler, and what came back."""

    class Once(serve.Handler):
        def __init__(self):
            self.rfile = io.BytesIO(request)
            self.wfile = io.BytesIO()
            self.client_address = ("127.0.0.1", 0)
            self.handle_one_request()

    return answer(Once().wfile.getvalue())


def answer(raw):
    """A raw response as the three things a test asks about."""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    code = int(lines[0].split()[1])
    headers = dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
    return code, headers, body.decode("utf-8", "replace")


def get(path, **headers):
    said = "".join("%s: %s\r\n" % (name.replace("_", "-"), value)
                   for name, value in headers.items())
    return ("GET %s HTTP/1.1\r\nHost: board\r\n%sConnection: close\r\n\r\n"
            % (path, said)).encode("utf-8")


def post(path, body="", length=None, **headers):
    said = "".join("%s: %s\r\n" % (name.replace("_", "-"), value)
                   for name, value in headers.items())
    return ("POST %s HTTP/1.1\r\nHost: board\r\nContent-Length: %d\r\n%s"
            "Connection: close\r\n\r\n%s"
            % (path, len(body) if length is None else length, said, body)).encode("utf-8")


# --- the pages ------------------------------------------------------------

@pytest.mark.database
def test_every_page_the_modules_publish_is_reachable(monkeypatch, db):
    # The route tables were a claim nobody checked for long enough that the
    # router stopped honouring them. Asking for each of them is what stops
    # that happening twice.
    lent(monkeypatch, db)
    for route in serve.ROUTES:
        if route.method != "GET":
            continue
        code, headers, body = asked(get(route.path))
        assert code == 200, route.path
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert body.startswith("<!doctype html>")


@pytest.mark.database
def test_the_root_is_the_week_and_not_a_holding_page(monkeypatch, db):
    lent(monkeypatch, db)
    _, _, body = asked(get("/"))
    assert "<h1>the week</h1>" in body


@pytest.mark.database
def test_a_form_posts_to_the_page_it_writes_to(monkeypatch, db):
    lent(monkeypatch, db)
    code, _, body = asked(post("/pantry", "do=add&ingredient=notional+rice&grade=staple"))
    assert code == 200
    assert "notional rice" in body


def test_a_page_that_does_not_take_a_post_says_so():
    code, _, body = asked(post("/groceries", "do=nothing"))
    assert code == 405
    assert "does not take a POST" in body


def test_a_path_on_no_table_is_not_a_page():
    code, _, _ = asked(get("/nowhere"))
    assert code == 404


# --- the writes a browser may make ---------------------------------------

def test_a_form_from_another_site_is_refused_before_anything_is_routed():
    # There is no login here and nothing to check a token against, so what
    # stops a page elsewhere binning a pantry row is the browser's own word
    # for where the form came from.
    code, _, body = asked(post("/pantry", "do=finished&ingredient=x",
                               Sec_Fetch_Site="cross-site"))
    assert code == 403
    assert "posted from this board" in body


@pytest.mark.database
def test_a_form_from_this_board_is_routed(monkeypatch, db):
    lent(monkeypatch, db)
    code, _, _ = asked(post("/pantry", "do=add&ingredient=notional+rice&grade=staple",
                            Sec_Fetch_Site="same-origin"))
    assert code == 200


def test_a_form_posted_from_another_site_is_refused_even_as_a_navigation():
    # A cross-site form post is a top-level navigation: the browser says
    # Sec-Fetch-Dest: document on it exactly as it does on a link. The
    # exemption that lets a mailed link open the week is read on a GET and on
    # no other verb, or it would be exempting the write it exists to refuse.
    code, _, body = asked(post("/pantry", "do=finished&ingredient=x",
                               Sec_Fetch_Site="cross-site", Sec_Fetch_Dest="document"))
    assert code == 403
    assert "posted from this board" in body


def test_a_read_from_another_site_is_refused_too():
    # A GET here can spend money: /groceries looks a dish up per cook against
    # a day's recipe points. So the guard is on both verbs, not just the one
    # that writes.
    code, _, body = asked(get("/groceries", Sec_Fetch_Site="cross-site"))
    assert code == 403
    assert "read from this board" in body


def test_a_navigation_from_another_site_is_refused_like_any_other_read():
    # No exemption for a top-level navigation. One would let a page elsewhere
    # send a browser to /groceries, the read that spends the day's points, and
    # the only thing it would buy is a link in a mail nobody has built.
    code, _, _ = asked(get("/groceries", Sec_Fetch_Site="cross-site",
                           Sec_Fetch_Dest="document"))
    assert code == 403


@pytest.mark.database
def test_a_board_opened_from_a_bookmark_is_let_through(monkeypatch, db):
    # A person typing the address or following a bookmark says 'none'.
    lent(monkeypatch, db)
    code, _, _ = asked(get("/", Sec_Fetch_Site="none", Sec_Fetch_Dest="document"))
    assert code == 200


def test_a_body_larger_than_a_form_is_not_read():
    code, _, _ = asked(post("/pantry", "x=1", length=serve.MOST_FORM_BYTES + 1))
    assert code == 413


def test_a_length_that_is_not_a_number_is_refused():
    code, _, body = asked(
        b"POST /pantry HTTP/1.1\r\nHost: board\r\nContent-Length: soon\r\n"
        b"Connection: close\r\n\r\n")
    assert code == 400
    assert "wants a length" in body


# --- the health the container is judged by -------------------------------

@pytest.mark.database
def test_health_is_ok_when_the_schema_is_where_we_left_it(monkeypatch, db):
    lent(monkeypatch, db)
    code, headers, body = asked(get("/health"))
    assert code == 200
    assert headers["Content-Type"] == "application/json"
    assert '"status": "ok"' in body


@pytest.mark.database
def test_a_pending_migration_reaches_the_checker_as_a_status_code(monkeypatch, db):
    # The checker calls urlopen and looks at nothing else, so a failure
    # written only into the body is a failure nobody reads.
    lent(monkeypatch, db)
    monkeypatch.setattr(psql, "pending", lambda cx: [(9, pathlib.Path("009-x.sql"))])
    code, _, body = asked(get("/health"))
    assert code == 503
    assert "migrations pending" in body
    assert "009-x.sql" in body


# --- what may reach the filesystem ---------------------------------------

def test_the_two_static_files_are_served_as_themselves():
    for path, kind in serve.STATIC_FILES.items():
        code, headers, _ = asked(get(path))
        assert code == 200, path
        assert headers["Content-Type"] == kind


def test_a_path_that_is_not_on_the_map_does_not_reach_the_filesystem():
    # The allowlist is the whole of the defence: a traversal is not a page on
    # it, so it is answered as no page at all rather than as a file read.
    for asking in ("/static/../serve.py", "/static/board.css/../../serve.py",
                   "/static/nothing.css"):
        code, _, _ = asked(get(asking))
        assert code == 404, asking


# --- a failure is a sentence ---------------------------------------------

@pytest.mark.database
def test_a_render_that_raises_answers_a_sentence_and_keeps_the_stack(monkeypatch, capsys, db):
    lent(monkeypatch, db)

    def falls_over(cx, query):
        raise RuntimeError("the connection string is postgresql://secret")

    monkeypatch.setitem(serve.RENDERS, ("/groceries", "GET"), falls_over)
    code, _, body = asked(get("/groceries"))
    assert code == 500
    assert body == "the board failed"
    # The evidence goes where `docker logs` finds it, and the page carries
    # none of it: an exception's own text here can name a database.
    assert "postgresql://secret" not in body
    assert "RuntimeError" in capsys.readouterr().err


# --- the tables themselves ------------------------------------------------

def test_the_router_wires_both_tables_and_nothing_twice():
    assert serve.ROUTES == plan_pages.ROUTES + pages.ROUTES
    assert len(serve.RENDERS) == len(serve.ROUTES)
    # "/" is the week rather than anything the board used to hold there.
    assert serve.RENDERS[("/", "GET")] is plan_pages.week_page
    # Every view a phone taps between answers, and the nav cannot point at a
    # page the router does not have.
    for path, _ in chrome.NAV:
        assert (path, "GET") in serve.RENDERS
