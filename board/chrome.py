"""The board's own vocabulary: the document, the words every view says, and the route.

Both view modules render into the same shell, escape through the same
function and read a posted form the same way. That vocabulary lives here
rather than inside one of them, so neither page module has to reach into its
sibling for it. A second set of these is two boards inside a fortnight, and
the first thing to go would be the escaping.

Nothing here opens a connection or knows what a socket is. A view is a plain
function of a connection and a parsed query that hands back a whole document,
and `Route` is how board/serve.py is told where one answers.
"""
import datetime
import decimal
import html
from collections.abc import Callable
from dataclasses import dataclass

from kitchen import pantry

# The pages, so each one can link to the others. The board is read on a phone
# and the four views are four taps apart or they are one view.
NAV = (("/", "the week"), ("/confirm", "the confirmations"),
       ("/pantry", "the pantry"), ("/settings", "the settings"))

MONTHS = ("january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december")


@dataclass(frozen=True)
class Route:
    """Where a view answers, and what answers there.

    `render` takes (cx, query) and hands back a whole document. A query is
    what urllib.parse.parse_qs makes: a name to a list of values, whether it
    came off the query string or a posted form body.
    """
    path: str
    method: str
    render: Callable[..., str]


def h(value: object) -> str:
    """Everything that reaches HTML, without exception.

    A pantry holds whatever someone typed into it, and an ingredient called
    `<script>` is a thing a person is entitled to write down.
    """
    return html.escape("" if value is None else str(value), quote=True)


def one(query: dict, name: str, default: str = "") -> str:
    """One value out of a parse_qs mapping, stripped.

    parse_qs drops a blank field instead of handing back an empty string, so
    an absent key and an emptied box arrive the same way. Here they mean the
    same thing.
    """
    values = query.get(name) or ()
    return values[0].strip() if values else default


def many(query: dict, name: str) -> list[str]:
    """Every value under one name: what a row of checkboxes sends."""
    return [value.strip() for value in query.get(name) or () if value.strip()]


def shell(title: str, body: str) -> str:
    """The document every view is rendered into.

    Both files it names are served from board/serve.py's own allowlist,
    because nothing is published and a CDN would be (pm/backlog.md).
    """
    return ("<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<link rel='stylesheet' href='/static/board.css'>"
            "<title>%s - AIoli</title>"
            "<main>%s</main>"
            "<script src='/static/board.js'></script>" % (h(title), body))


def nav(here: str | None = None) -> str:
    """The other views, because a phone has no back button worth using."""
    links = ["<a href='%s'>%s</a>" % (h(path), h(name))
             for path, name in NAV if path != here]
    return "<p class='quiet'>%s</p>" % " - ".join(links)


def needs_answer(text: str | None) -> str:
    """What went wrong, in the one colour the board keeps for being asked.

    Named for the class it writes rather than for the trouble it carries,
    because every view takes the trouble itself as `problem` and one of the
    two had to keep the word.
    """
    return "<p class='needs-answer'>%s</p>" % h(text) if text else ""


def state(text: str, marked: bool = False) -> str:
    """A row's state, marked when it wants looking at.

    The marked word is a span inside the state rather than a second class on
    it: `.row .state` is the more specific rule and would win, so `soon` on
    the same element would silently do nothing. This keeps the distinction
    inside the vocabulary board.css already has.
    """
    word = h(text)
    return "<span class='state'>%s</span>" % (
        "<span class='soon'>%s</span>" % word if marked else word)


def said(day: datetime.date, today: datetime.date) -> tuple[str, str]:
    """A date as it is spoken: the day, and how long ago it was."""
    behind = (today - day).days
    when = "%s %d %s" % (day.strftime("%A").lower(), day.day, MONTHS[day.month - 1])
    if behind == 0:
        return when, "today"
    if behind == 1:
        return when, "yesterday"
    if behind > 1:
        return when, "%d days ago" % behind
    return when, "in %d days" % -behind


def figure(value: object) -> str:
    """A stored quantity as a person would write it: 2, not 2.000."""
    if value is None:
        return ""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def whole(text: object, what: str, least: int = 0) -> int:
    """A whole number off a form, blaming the field rather than the parser."""
    try:
        number = int(str(text).strip())
    except (TypeError, ValueError):
        raise ValueError("%s wants a whole number, not %r" % (what, text)) from None
    if number < least:
        raise ValueError("%s cannot be less than %s" % (what, least))
    return number


def date(text: str, what: str) -> datetime.date | None:
    """A date off a form, or None for an empty box."""
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError("%s wants a date like 2026-09-20, not %r" % (what, text)) from None


def measure(text: str, what: str) -> decimal.Decimal | None:
    """A quantity off a form, as the exact decimal every quantity column holds,
    or None for an empty box - as `date` answers one."""
    if not text:
        return None
    try:
        return pantry.amount(text)
    except decimal.InvalidOperation:
        raise ValueError("%s wants a number, not %r" % (what, text)) from None
