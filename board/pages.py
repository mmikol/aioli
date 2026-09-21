"""The pantry, the settings and the confirmations: the half of the board a person edits.

Three views and the writes they make. Each one renders out of the kitchen
modules and writes back through kitchen/moves.py, so the ledger and the
balance never disagree - a board that wrote to `pantry` directly would be
exactly the kitchen that does not exist three weeks later (pm/backlog.md).

A view is a plain function of a connection and a parsed query that returns a
whole document. Nothing here opens a connection, commits one, or knows what a
socket is: board/serve.py wires the routes at the foot of this file, and the
caller owns the transaction, which is what lets the suite render every page
inside a transaction it throws away.

Three habits, stated once so no view has to repeat them.

Everything that reaches HTML goes through `_h`. A pantry holds whatever
someone typed into it, and an ingredient called `<script>` is a thing a person
is entitled to write down.

Every write is made at most once whatever the network does, which is what
kitchen/moves.py takes a `cause` for. A thumb that lands twice on a phone,
and a browser re-posting on a refresh, both arrive under a cause already
claimed and move the stock once. That is also why these handlers answer with
the page rather than a redirect: the usual reason to redirect after a post is
the double submit, and it is already answered. A pantry edit carries a cause
minted per form, because correcting the same ingredient twice is two real
edits and only the same form sent twice is one; a confirmation carries none,
because planner/week.py keys a meal on itself and a meal is cooked once.

Nothing Spoonacular authored is rendered here, which on these three pages is
easy: the pantry, the settings and the household's own answers are all the
household's (docs/db.md). The confirmation view reads a plan row's date and
slot and never its recipe pointer.
"""
import collections
import datetime
import decimal
import html
import secrets

from kitchen import moves, pantry, settings
from planner import week

# How near turning counts as soon. Three days is the horizon the board
# colours, and it is the same question the midweek mail asks.
SOON_DAYS = 3

# How far back a confirmation is still worth asking for. A meal from three
# weeks ago is not a question, it is an archaeology, and the answer would be
# a guess written into the ledger as a fact.
BEHIND_DAYS = 14

# A confirmation list is answered standing up, with one thumb: a list that
# scrolls is a list that gets the wrong row tapped. It is also the ceiling on
# what this view will ever hold in memory, which on a 16 GB host is a figure
# worth having rather than a query that returns whatever the plan holds.
AWAITING = 20

# The pages, so each one can link to the others. The board is read on a phone
# and the three views are three taps apart or they are one view.
NAV = (("/", "the week"), ("/confirm", "the confirmations"),
       ("/pantry", "the pantry"), ("/settings", "the settings"))

# The numbers the settings page shows, in the order they are read in: who
# eats, how long there is to cook, and how often the week is shopped for.
NUMBERS = (
    ("household_size", "how many the meals are for", 1),
    ("max_ready_minutes_weeknight", "the longest a weeknight cook may take", 1),
    ("max_ready_minutes_weekend", "the longest a weekend cook may take", 1),
    ("cook_sessions_per_week", "cook sessions a week", 0),
    ("shop_trips_per_week", "shopping trips a week", 0),
)

DAY_LISTS = (("cook_days", "the days the household cooks on"),
             ("shop_days", "the days the household shops on"))

# How a source reads to the person looking at it. The agent's is deliberately
# not a synonym of the other two: a figure that will one day arrive from the
# accountant should not look like one somebody typed.
ORIGINS = {"user": "typed", "default": "the default", "agent": "from another agent"}

MONTHS = ("january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december")


# --- the things every view needs -----------------------------------------

def _h(value):
    """Everything that reaches HTML, without exception."""
    return html.escape("" if value is None else str(value), quote=True)


def _one(query, name, default=""):
    """One value out of a parse_qs mapping, stripped.

    parse_qs drops a blank field rather than handing back an empty string, so
    an absent key and an emptied box arrive the same way, which is right:
    here they mean the same thing.
    """
    values = query.get(name) or ()
    return values[0].strip() if values else default


def _many(query, name):
    """Every value under one name, which is what a row of checkboxes sends."""
    return [value.strip() for value in query.get(name) or () if value.strip()]


def _whole(text, what, least=0):
    """A whole number off a form, blaming the field rather than the parser."""
    try:
        number = int(str(text).strip())
    except (TypeError, ValueError):
        raise ValueError("%s wants a whole number, not %r" % (what, text)) from None
    if number < least:
        raise ValueError("%s cannot be less than %s" % (what, least)) from None
    return number


def _measure(text, what):
    """A quantity off a form, as the exact decimal every quantity column holds."""
    try:
        return pantry.amount(text)
    except decimal.InvalidOperation:
        raise ValueError("%s wants a number, not %r" % (what, text)) from None


def _figure(value):
    """A stored quantity as a person would write it: 2, and not 2.000."""
    if value is None:
        return ""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _cause(what):
    """A fresh idempotency key for one form.

    Minted at render and carried in the form, so the second half of a
    double-tap arrives under a cause kitchen/moves.py has already claimed and
    changes nothing, while the next honest edit of the same row arrives under
    a new one. Nothing is kept here: the ledger's note is the whole record of
    which causes have been spent.
    """
    return "board:%s:%s" % (what, secrets.token_hex(6))


def shell(title, body):
    """The document every view is rendered into.

    The same head as board/serve.py's own page, and one script. Both files
    are served from here: nothing is published and a CDN would be
    (pm/backlog.md).
    """
    return ("<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<link rel='stylesheet' href='/static/board.css'>"
            "<title>%s - AIoli</title>"
            "<main>%s</main>"
            "<script src='/static/board.js'></script>" % (_h(title), body))


def _nav(here=None):
    """The other views, because a phone has no back button worth using."""
    links = ["<a href='%s'>%s</a>" % (_h(path), _h(name))
             for path, name in NAV if path != here]
    return "<p class='quiet'>%s</p>" % " - ".join(links)


def _problem(text):
    """What went wrong, in the one colour the board keeps for being asked."""
    return "<p class='needs-answer'>%s</p>" % _h(text) if text else ""


def _state(text, marked=False):
    """A row's state, marked when it wants looking at.

    The marked word is a span inside the state rather than a second class on
    it: `.row .state` is the more specific rule and would win, so `soon` on
    the same element would silently do nothing. This keeps the distinction
    inside the vocabulary board.css already has and restyles nothing.
    """
    said = _h(text)
    return "<span class='state'>%s</span>" % (
        "<span class='soon'>%s</span>" % said if marked else said)


def _said(day, today):
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


# --- the pantry -----------------------------------------------------------

def pantry_page(cx, query=None, problem=None, today=None):
    """What is in the house: the perishables by what turns soonest, then the staples.

    One line per name rather than one per row. The ledger moves stock by name
    and takes the lot nearest turning (kitchen/pantry.py `find`), so a button
    on a line acts on the lot that line is showing; a line per row would offer
    a button that quietly moved a different chicken.
    """
    today = today or datetime.date.today()
    lots = _lots(pantry.in_stock(cx))
    soon = {row["id"] for row in pantry.turning_soonest(cx, within_days=SOON_DAYS, today=today)}
    # Grouped by name, but read by date: what turns soonest is the whole
    # question this list answers, and the staples have no date to sort on.
    perishable = sorted((each for each in lots if each[0]["grade"] == pantry.PERISHABLE),
                        key=lambda each: (each[0]["turns_on"] is None,
                                          each[0]["turns_on"] or datetime.date.max,
                                          each[0]["ingredient"].lower()))
    staple = [each for each in lots if each[0]["grade"] == pantry.STAPLE]

    body = ["<h1>the pantry</h1>", _nav("/pantry"), _problem(problem),
            "<h2>what turns soonest</h2>"]
    body.append("".join(_perishable_row(row, count, today, soon) for row, count in perishable)
                or "<p class='quiet'>nothing perishable is written down.</p>")
    body.append("<h2>the staples</h2>")
    body.append("".join(_staple_row(row, count) for row, count in staple)
                or "<p class='quiet'>no staples are written down.</p>")
    body.append(_add_form(today))
    return shell("the pantry", "".join(body))


def _lots(rows):
    """The house's stock as one line per name, carrying the lot nearest turning.

    Two chickens bought a week apart are one line that says there are two:
    they turn a week apart and the older one is the one being ranked, cooked
    and asked about, so it is the one shown.
    """
    order = sorted(rows, key=lambda row: (row["ingredient"].lower(),
                                          row["turns_on"] is None,
                                          row["turns_on"] or datetime.date.min,
                                          row["id"]))
    lines, seen = [], {}
    for row in order:
        name = row["ingredient"].lower()
        if name in seen:
            lines[seen[name]][1] += 1
            continue
        seen[name] = len(lines)
        lines.append([row, 1])
    return [(row, count) for row, count in lines]


def _turns(row, today):
    """When a perishable turns, said the way it is asked about.

    A row with no date cannot be ranked and is not guessed at: the planner's
    whole waste term rests on this arithmetic, so a made-up day would be a
    made-up plan (kitchen/pantry.py).
    """
    if row["turns_on"] is None:
        return "no date"
    left = (row["turns_on"] - today).days
    if left < 0:
        return "turned %d days ago" % -left
    return {0: "turns today", 1: "turns tomorrow"}.get(left, "turns in %d days" % left)


def _perishable_row(row, count, today, soon):
    """A perishable: what it is, how much, when it turns, and the two words for gone."""
    name, cause = row["ingredient"], _cause("pantry")
    held = ("%s %s" % (_figure(row["quantity"]), row["unit"] or "")).strip()
    lots = " - %d lots" % count if count > 1 else ""
    return (
        "<div class='row'>"
        "<span class='name'>%s<span class='quiet'> - %s%s</span></span>"
        "%s"
        "<form method='post' action='/pantry'>"
        "<input type='hidden' name='ingredient' value='%s'>"
        "<input type='hidden' name='cause' value='%s'>"
        "<button name='do' value='finished'>finished</button>"
        "<button name='do' value='discarded'>binned</button>"
        "</form>"
        "<details><summary>correct</summary>"
        "<form method='post' action='/pantry'>"
        "<input type='hidden' name='do' value='correct'>"
        "<input type='hidden' name='ingredient' value='%s'>"
        "<input type='hidden' name='cause' value='%s'>"
        "<label>what is left <input name='quantity' inputmode='decimal' value='%s'></label> "
        "<label>in <input name='unit' size='6' value='%s'></label> "
        "<button class='primary' type='submit'>save</button>"
        "</form></details>"
        "</div>" % (_h(name), _h(held), _h(lots),
                    _state(_turns(row, today), row["id"] in soon),
                    _h(name), _h(cause), _h(name), _h(_cause("pantry")),
                    _h(_figure(row["quantity"])), _h(row["unit"] or "")))


def _staple_row(row, count):
    """A staple: in stock or running low, and nothing more precise than that.

    Nobody weighs their rice, and a pantry that asks them to is a pantry
    abandoned inside a fortnight (pm/backlog.md).
    """
    name, cause = row["ingredient"], _cause("pantry")
    level = {"in_stock": "in stock", "low": "running low", "out": "out"}.get(
        row["level"], row["level"] or "")
    lots = "<span class='quiet'> - %d lots</span>" % count if count > 1 else ""
    choices = "".join(
        "<option value='%s'%s>%s</option>"
        % (_h(each), " selected" if each == row["level"] else "",
           _h({"in_stock": "in stock", "low": "running low", "out": "out"}[each]))
        for each in pantry.LEVELS)
    return (
        "<div class='row'>"
        "<span class='name'>%s%s</span>"
        "%s"
        "<form method='post' action='/pantry'>"
        "<input type='hidden' name='ingredient' value='%s'>"
        "<input type='hidden' name='cause' value='%s'>"
        "<button name='do' value='finished'>finished</button>"
        "<button name='do' value='discarded'>binned</button>"
        "</form>"
        "<details><summary>correct</summary>"
        "<form method='post' action='/pantry'>"
        "<input type='hidden' name='do' value='correct'>"
        "<input type='hidden' name='ingredient' value='%s'>"
        "<input type='hidden' name='cause' value='%s'>"
        "<label>it is <select name='level'>%s</select></label> "
        "<button class='primary' type='submit'>save</button>"
        "</form></details>"
        "</div>" % (_h(name), lots, _state(level, row["level"] == "low"),
                    _h(name), _h(cause), _h(name), _h(_cause("pantry")), choices))


def _add_form(today):
    """Booking something in.

    The two ways a thing arrives are different words in the ledger and the
    same arithmetic: a shop is `bought` and a cupboard being written down for
    the first time is `corrected`. The waste figure and, later, the spend are
    read off that difference, so the form asks rather than assuming a shop.
    """
    return (
        "<h2>add something</h2>"
        "<form method='post' action='/pantry' data-add>"
        "<input type='hidden' name='do' value='add'>"
        "<input type='hidden' name='cause' value='%s'>"
        "<div class='row'>"
        "<label class='name'>what <input name='ingredient' required></label>"
        "<label>it is a <select name='grade'>"
        "<option value='perishable'>perishable</option>"
        "<option value='staple'>staple</option>"
        "</select></label>"
        "<label>it was <select name='how'>"
        "<option value='bought'>bought</option>"
        "<option value='found'>already in the house</option>"
        "</select></label>"
        "</div>"
        "<div class='row' data-only='perishable'>"
        "<label class='name'>how much <input name='quantity' inputmode='decimal'></label>"
        "<label>in <input name='unit' size='6'></label>"
        "<label>keeps <input name='shelf_life_days' inputmode='numeric' size='4'> days</label>"
        "<label>since <input name='acquired_on' type='date' value='%s'></label>"
        "</div>"
        "<div class='row'><button class='primary' type='submit'>add it</button></div>"
        "</form>" % (_h(_cause("pantry")), _h(today.isoformat())))


def pantry_edit(cx, query):
    """One edit, and then the pantry as it now stands.

    Every branch goes through kitchen/moves.py: the balance and the ledger
    move together or neither moves. A bad field is answered with the page and
    the reason rather than an error, because the page is where it gets fixed.
    """
    try:
        name = _one(query, "ingredient")
        if not name:
            raise ValueError("an edit wants an ingredient")
        cause = _one(query, "cause") or None
        doing = _one(query, "do")
        if doing == "finished":
            moves.finished(cx, name, cause=cause)
        elif doing == "discarded":
            moves.discarded(cx, name, cause=cause)
        elif doing == "correct":
            _correct(cx, query, name, cause)
        elif doing == "add":
            _add(cx, query, name, cause)
        else:
            raise ValueError("the pantry cannot %r" % doing)
    except ValueError as bad:
        return pantry_page(cx, query, problem=str(bad))
    return pantry_page(cx, query)


def _correct(cx, query, name, cause):
    """What is actually on the shelf, whatever the arithmetic thinks."""
    level = _one(query, "level") or None
    if level is not None and level not in pantry.LEVELS:
        raise ValueError("a level is one of %s, not %r" % (", ".join(pantry.LEVELS), level))
    quantity = _one(query, "quantity")
    moves.corrected(cx, name, level=level, unit=_one(query, "unit") or None,
                    quantity=_measure(quantity, "the quantity") if quantity else None,
                    cause=cause)


def _add(cx, query, name, cause):
    """Book a thing in, as the grade it is and by the word that is true of it."""
    grade = _one(query, "grade", pantry.PERISHABLE)
    if grade not in pantry.GRADES:
        raise ValueError("a grade is one of %s, not %r" % (", ".join(pantry.GRADES), grade))
    bought = _one(query, "how", "bought") == "bought"
    if grade == pantry.STAPLE:
        # A staple arriving is in stock. Saying it is already low is the row's
        # own correction, and doing it here would be two ledger lines for one
        # act - `restock` brings a staple back to in_stock whatever it is told.
        record = moves.bought if bought else moves.corrected
        return record(cx, name, cause=cause)

    quantity = _one(query, "quantity")
    unit = _one(query, "unit")
    if not quantity or not unit:
        raise ValueError("a perishable is measured: %s wants a quantity and a unit" % name)
    shelf_life = _one(query, "shelf_life_days")
    held = pantry.find(cx, name)
    if not shelf_life and (held is None or held["shelf_life_days"] is None):
        # Not optional, although the column allows a null: the shelf life is
        # what makes ageing stock rank ahead of fresh, and a row without one
        # is invisible to the planner it was entered for.
        raise ValueError("%s wants a shelf life in days: it is what makes it rank as ageing"
                         % name)
    record = moves.bought if bought else moves.corrected
    return record(cx, name, quantity=_measure(quantity, "the quantity"), unit=unit,
                  shelf_life_days=_whole(shelf_life, "the shelf life", 0) if shelf_life else None,
                  acquired_on=_date(_one(query, "acquired_on"), "the date it came in"),
                  cause=cause)


def _date(text, what):
    """A date off a form, or None for an empty box."""
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError("%s wants a date like 2026-09-20, not %r" % (what, text)) from None


# --- the settings ---------------------------------------------------------

def settings_page(cx, query=None, problem=None):
    """The household's facts, each one saying where it came from.

    The source is shown on every figure because the day one of them starts
    arriving from the accountant is a change of source and not a migration
    (docs/fleet.md), and a board that showed only the number would make that
    day look like nothing had happened.
    """
    body = ["<h1>the settings</h1>", _nav("/settings"), _problem(problem),
            "<form method='post' action='/settings'>",
            "<input type='hidden' name='do' value='save'>"]
    for key, what, least in NUMBERS:
        body.append(_number_row(cx, key, what, least))
    for key, what in DAY_LISTS:
        body.append(_days_row(cx, key, what))
    body.append("<div class='row'><button class='primary' type='submit'>save</button></div>"
                "</form>")
    body.append(_rules(cx))
    body.append(_kitchen(cx))
    return shell("the settings", "".join(body))


def _origin(cx, key):
    """Where a value came from, worded so it does not read as the value itself.

    The agent's source is marked as well as worded, inside the row's own
    state, so the distinction costs the stylesheet nothing.
    """
    source = settings.origin(cx, key)
    return _state(ORIGINS.get(source, source), marked=source == "agent")


def _number_row(cx, key, what, least):
    """One figure, its box and its source.

    The hidden `fields` input is what tells the handler this form carried the
    key at all: an untouched key and an emptied box are the same absence in a
    posted form, and writing the difference away would be the board quietly
    changing a setting nobody looked at.
    """
    return ("<input type='hidden' name='fields' value='%s'>"
            "<div class='row'>"
            "<label class='name' for='%s'>%s</label>"
            "<input id='%s' name='%s' type='number' inputmode='numeric' min='%s' value='%s'>"
            "%s</div>"
            % (_h(key), _h(key), _h(what), _h(key), _h(key), _h(least),
               _h(settings.get(cx, key)), _origin(cx, key)))


def _days_row(cx, key, what):
    """A day list as seven boxes, because nobody should have to spell wednesday."""
    stored = settings.get(cx, key)
    try:
        chosen, unreadable = set(settings.days(stored)), ""
    except ValueError:
        # A day list the household cannot read is a week nobody scheduled, and
        # a page that raised over it would be the one page able to fix it.
        chosen = set()
        unreadable = "<p class='needs-answer'>%s is unreadable: %s</p>" % (_h(key), _h(stored))
    boxes = "".join(
        "<label><input type='checkbox' name='%s' value='%s'%s> %s</label> "
        % (_h(key), _h(day), " checked" if day in chosen else "", _h(day))
        for day in settings.WEEK)
    return ("<input type='hidden' name='fields' value='%s'>"
            "<div class='row'><span class='name'>%s</span>%s</div>"
            "<div class='row'>%s</div>%s"
            % (_h(key), _h(what), _origin(cx, key), boxes, unreadable))


def _rules(cx):
    """What will not be eaten, and what that sends to the search."""
    rows = []
    for rule in settings.dietary_rules(cx):
        rows.append(
            "<div class='row'>"
            "<span class='name'>%s<span class='quiet'> - %s</span></span>"
            "%s"
            "<form method='post' action='/settings'>"
            "<input type='hidden' name='do' value='drop-rule'>"
            "<input type='hidden' name='kind' value='%s'>"
            "<input type='hidden' name='value' value='%s'>"
            "<button type='submit'>lift it</button>"
            "</form></div>"
            % (_h(rule["value"]), _h(rule["kind"]), _state(rule["note"] or ""),
               _h(rule["kind"]), _h(rule["value"])))
    filters = settings.recipe_filters(cx)
    sends = "the search sends diet %s, intolerances %s, and excludes %s" % (
        filters["diet"] or "nothing",
        ", ".join(filters["intolerances"]) or "nothing",
        ", ".join(filters["exclude_ingredients"]) or "nothing")
    kinds = "".join("<option value='%s'>%s</option>" % (_h(kind), _h(kind))
                    for kind in settings.KINDS)
    return ("<h2>what will not be eaten</h2>"
            + ("".join(rows) or "<p class='quiet'>nothing is ruled out.</p>")
            + "<p class='quiet'>%s</p>" % _h(sends)
            + "<form method='post' action='/settings'><div class='row'>"
              "<input type='hidden' name='do' value='add-rule'>"
              "<label class='name'>what <input name='value' required></label>"
              "<label>as a <select name='kind'>%s</select></label>"
              "<label>note <input name='note' size='10'></label>"
              "<button class='primary' type='submit'>add it</button>"
              "</div></form>" % kinds)


def _kitchen(cx):
    """What the kitchen has.

    Absent and unlisted are not the same thing and the two buttons say so: a
    row reading `not here` is the household stating it does not own the thing,
    which is what drops a recipe, while forgetting the row says nothing either
    way and lets every recipe through again (kitchen/settings.py).
    """
    rows = []
    for kit in settings.equipment(cx):
        rows.append(
            "<div class='row'>"
            "<span class='name'>%s</span>"
            "%s"
            "<form method='post' action='/settings'>"
            "<input type='hidden' name='name' value='%s'>"
            "<input type='hidden' name='present' value='%s'>"
            "<button name='do' value='set-equipment'>%s</button>"
            "<button name='do' value='drop-equipment'>forget it</button>"
            "</form></div>"
            % (_h(kit["name"]),
               _state("in the kitchen" if kit["present"] else "not here",
                      marked=not kit["present"]),
               _h(kit["name"]), "" if kit["present"] else "yes",
               "say it is gone" if kit["present"] else "say it is here"))
    return ("<h2>the kitchen</h2>"
            + ("".join(rows) or "<p class='quiet'>nothing is written down, "
                                "which lets every recipe through.</p>")
            + "<form method='post' action='/settings'><div class='row'>"
              "<input type='hidden' name='do' value='set-equipment'>"
              "<input type='hidden' name='present' value='yes'>"
              "<label class='name'>what <input name='name' required></label>"
              "<button class='primary' type='submit'>add it</button>"
              "</div></form>")


def settings_edit(cx, query):
    """One change to the household's facts, and then the settings as they stand."""
    try:
        doing = _one(query, "do")
        if doing == "save":
            _save(cx, query)
        elif doing == "add-rule":
            value = _one(query, "value")
            if not value:
                raise ValueError("a rule wants something to rule out")
            settings.add_dietary_rule(cx, _one(query, "kind"), value,
                                      _one(query, "note") or None)
        elif doing == "drop-rule":
            settings.remove_dietary_rule(cx, _one(query, "kind"), _one(query, "value"))
        elif doing == "set-equipment":
            name = _one(query, "name")
            if not name:
                raise ValueError("a piece of kit wants a name")
            settings.add_equipment(cx, name, present=bool(_one(query, "present")))
        elif doing == "drop-equipment":
            settings.remove_equipment(cx, _one(query, "name"))
        else:
            raise ValueError("the settings cannot %r" % doing)
    except ValueError as bad:
        return settings_page(cx, query, problem=str(bad))
    return settings_page(cx, query)


def _save(cx, query):
    """Write what changed, and only what changed.

    Saving every box would turn every default into a typed figure the first
    time anyone pressed save, and the board would lose the one thing the
    source column is for - being able to say which figures the household has
    actually decided.

    Everything is read and checked before anything is written: half a saved
    form is worse than a rejected one, because nothing says which half.
    """
    carried = set(_many(query, "fields"))
    wanted = {}
    for key, what, least in NUMBERS:
        if key in carried:
            wanted[key] = str(_whole(_one(query, key), what, least))
    for key, _what in DAY_LISTS:
        if key in carried:
            wanted[key] = ",".join(settings.days(",".join(_many(query, key))))
    for key, value in wanted.items():
        if value != (settings.get(cx, key) or ""):
            settings.put(cx, key, value, source="user")


# --- the confirmations ---------------------------------------------------
#
# The plan is the planner's. This view reads what is still owed an answer and
# hands the answer straight back to planner/week.py, which already knows that
# skipping a meal empties it, that a portion of an earlier cook moves no stock
# of its own, and that the cause for all of it is 'plan_meal:<id>'. The board
# asking those questions again in its own SQL is how the two would drift.
#
# What is read is the date, the slot, the servings and what kind of slot it
# is. The recipe pointer on a live row is the plan's business and is never
# rendered here (docs/db.md).

# A week being eaten is in neither of these. A 'closed' week has had its
# pointers purged and its questions are long past; an 'unfilled' one is the
# planner saying plainly it could not plan, so there is nothing in it to
# confirm. A draft is asked about: it is a week in the making, and a board
# that stayed silent about one would look exactly like a board with nothing
# to ask.
NOT_BEING_EATEN = ("closed", "unfilled")

Meal = collections.namedtuple("Meal", "id on slot servings kind")


def _planned(cx):
    """Whether there is a week to be asked about at all.

    The table is asked after rather than assumed: a board running against a
    database that has not been migrated yet should say the week is not planned
    and stay usable, not fall over on the one view a phone opens.
    """
    if cx.execute("select to_regclass('plan_meal') as found").fetchone()["found"] is None:
        return False
    return cx.execute("select 1 from plan where state <> all (%s) limit 1",
                      (list(NOT_BEING_EATEN),)).fetchone() is not None


def awaiting(cx, today=None):
    """The meals still owed a 'did you cook this', oldest first.

    The standing assumption is that an unconfirmed meal did not happen
    (pm/backlog.md), so what is asked about is what is already behind: today
    and the fortnight before it. Thursday is not a question on Tuesday, and a
    meal from last month is not a question at all - the answer would be a
    guess, and it would be written into the ledger as a fact.

    A slot with no kind is a slot nothing fills, which is a row worth showing
    on the week and not a question with a true answer, so it is not asked
    about. Lunch comes before dinner, as it does in the plan's own reading.
    """
    today = today or datetime.date.today()
    if not _planned(cx):
        return []
    rows = cx.execute(
        "select meal.id, meal.meal_on, meal.slot, meal.servings, meal.kind"
        " from plan_meal meal join plan on plan.id = meal.plan_id"
        " where meal.meal_on between %s and %s and meal.kind is not null"
        " and not meal.skipped and meal.cooked_at is null and plan.state <> all (%s)"
        " order by meal.meal_on, case meal.slot when 'lunch' then 0 else 1 end, meal.id"
        " limit %s",
        (today - datetime.timedelta(days=BEHIND_DAYS), today, list(NOT_BEING_EATEN),
         AWAITING)).fetchall()
    return [Meal(row["id"], row["meal_on"], row["slot"], row["servings"], row["kind"])
            for row in rows]


def confirm_page(cx, query=None, problem=None, today=None):
    """The meals waiting on an answer, with the two buttons that give it.

    Answered standing in a kitchen, on a phone, so there is one question per
    row and two targets to hit. The row is marked as needing an answer in the
    one colour the board keeps for that.
    """
    today = today or datetime.date.today()
    meals = awaiting(cx, today)
    body = ["<h1>the confirmations</h1>", _nav("/confirm"), _problem(problem)]
    if meals:
        body.append("".join(_meal_row(meal, today) for meal in meals))
    elif _planned(cx):
        body.append("<p class='quiet'>nothing is waiting on an answer.</p>")
    else:
        body.append("<p class='quiet'>the week is not planned yet, "
                    "so there is nothing to confirm.</p>")
    return shell("the confirmations", "".join(body))


def _meal_row(meal, today):
    """One meal, one question, two answers.

    A portion of an earlier cook is asked whether it was eaten and not
    whether it was cooked, because it was cooked on another day and the
    question would be about the wrong evening.

    There is no cause in this form. Everywhere else on the board one is minted
    per render, because correcting the same ingredient twice is two real
    edits; a meal is cooked once, ever, so planner/week.py keys it on the meal
    itself and a phone that sent the answer, lost the tailnet and sent it
    again moves the stock once.
    """
    when, behind = _said(meal.on, today)
    for_how_many = " for %s" % meal.servings if meal.servings else ""
    eaten = meal.kind == "leftovers"
    return (
        "<div class='row'>"
        "<span class='name needs-answer'>%s%s<span class='quiet'> - %s%s</span></span>"
        "%s"
        "<form method='post' action='/confirm'>"
        "<input type='hidden' name='meal' value='%s'>"
        "<button class='primary' name='answer' value='cooked'>%s</button>"
        "<button name='answer' value='skipped'>did not</button>"
        "</form></div>"
        % (_h(meal.slot), _h(for_how_many), _h(when),
           " - leftovers" if eaten else "", _state(behind),
           _h(meal.id), "ate it" if eaten else "cooked it"))


def confirm_answer(cx, query):
    """One answer, handed to the plan, and then whatever is still waiting.

    Both answers are the planner's own functions rather than an update
    written here. Skipping a meal empties it and empties whatever was going to
    eat its second portion; confirming one moves the stock under
    'plan_meal:<id>' and knows a portion of an earlier cook moves none. A
    board that wrote those rules a second time would be a board that drifts
    from them.

    No ingredients go with the confirmation: a meal's ingredients are the
    recipe's words, which are not ours to keep (docs/db.md), so the board has
    no list of its own to subtract. They are passed by whoever is holding the
    method it fetched at the stove, which is the backlog item after this one.
    """
    try:
        said = _one(query, "answer")
        if said not in ("cooked", "skipped"):
            raise ValueError("an answer is cooked or skipped, not %r" % said)
        meal = _whole(_one(query, "meal"), "the meal")
        if said == "cooked":
            week.confirm_cooked(cx, meal)
        else:
            week.skip(cx, meal)
    except ValueError as bad:
        return confirm_page(cx, query, problem=str(bad))
    return confirm_page(cx, query)


# --- what board/serve.py wires -------------------------------------------

Route = collections.namedtuple("Route", "path method render")

# Every render takes (cx, query) and hands back a whole document. A query is
# what urllib.parse.parse_qs makes: a name to a list of values, whether it
# came off the query string or a posted form body.
ROUTES = (
    Route("/pantry", "GET", pantry_page),
    Route("/pantry", "POST", pantry_edit),
    Route("/settings", "GET", settings_page),
    Route("/settings", "POST", settings_edit),
    Route("/confirm", "GET", confirm_page),
    Route("/confirm", "POST", confirm_answer),
)
