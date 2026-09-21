"""The pantry, the settings and the confirmations: the half of the board a person edits.

Three views and the writes they make. Each one renders out of the kitchen
modules and writes back through kitchen/moves.py, so the ledger and the
balance never disagree - a board that wrote to `pantry` directly would be
exactly the kitchen that does not exist three weeks later (pm/backlog.md).

A view is a plain function of a connection and a parsed query that returns a
whole document. Nothing here opens a connection, commits one, or knows what a
socket is: board/serve.py wires the routes at the foot of this file, and the
connection it hands in is the transaction. That is what lets the suite render
every page inside a transaction it throws away.

Three habits, stated once so no view has to repeat them.

Everything that reaches HTML goes through `board.chrome.h`, which is where the
document, the nav and the rest of the board's shared words live as well. A
pantry holds whatever someone typed into it, and an ingredient called
`<script>` is a thing a person is entitled to write down.

kitchen/moves.py takes a `cause` so every write is made at most once whatever
the network does. A thumb that lands twice on a phone, and a browser
re-posting on a refresh, both arrive under a cause already claimed and move
the stock once. That is also why these handlers answer with the page instead
of a redirect: the usual reason to redirect after a post is the double
submit, and it is already answered. A pantry edit carries a cause minted per
form, because correcting the same ingredient twice is two real edits and only
the same form sent twice is one; a confirmation carries none, because
planner/week.py keys a meal on itself and a meal is cooked once.

A post from another site never reaches these handlers. board/serve.py refuses
one before it routes, on what the browser itself says about where the form
came from: this board has no login and nothing to check a token against, so
the alternative would be a page elsewhere making a browser on the tailnet bin
a pantry row.

Nothing Spoonacular authored is rendered here, and on these three pages that
is easy: the pantry, the settings and the household's own answers are all the
household's (docs/db.md). The confirmation view reads a plan row's date and
slot and never its recipe pointer - it follows the pointer to the stove to
find out what a cook took out of the cupboard, and what comes back is matched
against the household's own names, subtracted and dropped.
"""
import datetime
import secrets
from dataclasses import dataclass

from board.chrome import (
    Route,
    date,
    figure,
    h,
    many,
    measure,
    nav,
    needs_answer,
    one,
    said,
    shell,
    state,
    whole,
)
from kitchen import moves, one_of, pantry, settings
from planner import week
from recipes import steps
from recipes.client import usage_into

# How near turning counts as soon. Three days is the horizon the board
# colours, and it is the question the midweek mail will ask when that item
# lands (pm/backlog.md).
SOON_DAYS = 3

# How far back a confirmation is still worth asking for. A meal from three
# weeks ago is not a question, it is an archaeology, and the answer would be
# a guess written into the ledger as a fact.
BEHIND_DAYS = 14

# A confirmation list is answered standing up, with one thumb: a list that
# scrolls is a list that gets the wrong row tapped. It is also the ceiling on
# what this view will ever hold in memory, and on a 16 GB host a ceiling beats
# a query that returns whatever the plan holds.
AWAITING = 20

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

# A staple's whole vocabulary, in the words a person reads. Written once
# because the row and the correcting form both say it.
LEVELS_SAID = {"in_stock": "in stock", "low": "running low", "out": "out"}

# One stove for the life of the process, because the hour it holds is only
# worth having if the next request finds it (recipes/steps.py). A
# confirmation arriving from a phone is one more request, and the meal being
# confirmed is usually the one whose method was opened at the pan an hour
# ago, so the answer is already in hand and costs nothing.
STOVE = steps.Stove()


# --- what only the editing views need ------------------------------------

def _cause(what):
    """A fresh idempotency key for one form.

    Minted at render and carried in the form, so the second half of a
    double-tap arrives under a cause kitchen/moves.py has already claimed and
    changes nothing, while the next honest edit of the same row arrives under
    a new one. Nothing is kept here: the ledger's note is the whole record of
    which causes have been spent.
    """
    return "%s%s:%s" % (moves.BOARD, what, secrets.token_hex(6))


# --- the pantry -----------------------------------------------------------

def pantry_page(cx, query: dict | None = None, problem: str | None = None,
       today: datetime.date | None = None) -> str:
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

    body = ["<h1>the pantry</h1>", nav("/pantry"), needs_answer(problem),
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


def _pantry_row(name, said, shown, correcting):
    """One line of the pantry: what it is, what state it is in, and the two
    ways it can go.

    The two grades differ in three places - what is said quietly beside the
    name, what state the row is in, and the one field that corrects it - and
    in nothing else, so the line is written once and those three are handed
    in. A cause is minted per form rather than per row, because correcting a
    thing and saying it is finished are two edits.
    """
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
        "%s"
        "<button class='primary' type='submit'>save</button>"
        "</form></details>"
        "</div>" % (h(name), said, shown,
                    h(name), h(_cause("pantry")),
                    h(name), h(_cause("pantry")), correcting))


def _perishable_row(row, count, today, soon):
    """A perishable: what it is, how much, when it turns, and the two words for gone."""
    held = ("%s %s" % (figure(row["quantity"]), row["unit"] or "")).strip()
    lots = " - %d lots" % count if count > 1 else ""
    return _pantry_row(
        row["ingredient"],
        "<span class='quiet'> - %s%s</span>" % (h(held), h(lots)),
        state(_turns(row, today), row["id"] in soon),
        "<label>what is left <input name='quantity' inputmode='decimal' value='%s'></label> "
        "<label>in <input name='unit' size='6' value='%s'></label> "
        % (h(figure(row["quantity"])), h(row["unit"] or "")))


def _staple_row(row, count):
    """A staple: in stock or running low.

    Nobody weighs their rice, and a pantry that asks them to is a pantry
    abandoned inside a fortnight (pm/backlog.md).
    """
    lots = "<span class='quiet'> - %d lots</span>" % count if count > 1 else ""
    choices = "".join(
        "<option value='%s'%s>%s</option>"
        % (h(each), " selected" if each == row["level"] else "",
           h(LEVELS_SAID[each]))
        for each in pantry.LEVELS)
    return _pantry_row(
        row["ingredient"], lots,
        state(LEVELS_SAID.get(row["level"], row["level"] or ""), row["level"] == "low"),
        "<label>it is <select name='level'>%s</select></label> " % choices)


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
        "</form>" % (h(_cause("pantry")), h(today.isoformat())))


def pantry_edit(cx, query: dict) -> str:
    """One edit, and then the pantry as it now stands.

    Every branch goes through kitchen/moves.py: the balance and the ledger
    move together or neither moves. A bad field is answered with the page and
    the reason rather than an error, because the page is where it gets fixed.
    """
    try:
        name = one(query, "ingredient")
        if not name:
            raise ValueError("an edit wants an ingredient")
        cause = one(query, "cause") or None
        if cause is not None and not cause.startswith(moves.BOARD):
            # A cause is an at-most-once key in one flat namespace
            # (kitchen/moves.py), so a form carrying 'plan_meal:184' would
            # claim the key a confirmation needs and leave that meal marked
            # cooked with nothing subtracted. The board mints its own and
            # takes no other.
            raise ValueError("that edit did not come from a form on this board")
        doing = one(query, "do")
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
    level = one(query, "level") or None
    if level is not None:
        # Checked here although kitchen/pantry.py checks it too: `correct`
        # only reaches its own check where the house already holds the thing,
        # and a level nobody recognises would otherwise book a new staple
        # rather than be refused. The words are the kitchen's either way.
        one_of(level, pantry.LEVELS, "level")
    quantity = one(query, "quantity")
    moves.corrected(cx, name, level=level, unit=one(query, "unit") or None,
                    quantity=measure(quantity, "the quantity"),
                    cause=cause)


def _add(cx, query, name, cause):
    """Book a thing in, as the grade it is and by the word that is true of it."""
    # The grade is the form's choice and the branch below turns on it, so it
    # is refused here rather than downstream, where `restock` would infer a
    # plausible one from the other fields. The refusal is the kitchen's own.
    grade = one_of(one(query, "grade", pantry.PERISHABLE), pantry.GRADES, "grade")
    bought = one(query, "how", "bought") == "bought"
    if grade == pantry.STAPLE:
        # A staple arriving is in stock. Saying it is already low is the row's
        # own correction, and doing it here would be two ledger lines for one
        # act - `restock` brings a staple back to in_stock whatever it is told.
        book = moves.bought if bought else moves.corrected
        return book(cx, name, grade=grade, cause=cause)

    quantity = one(query, "quantity")
    unit = one(query, "unit")
    if not quantity or not unit:
        raise ValueError("a perishable is measured: %s wants a quantity and a unit" % name)
    shelf_life = one(query, "shelf_life_days")
    held = pantry.find(cx, name)
    if not shelf_life and (held is None or held["shelf_life_days"] is None):
        # Not optional, although the column allows a null: the shelf life is
        # what makes ageing stock rank ahead of fresh, and a row without one
        # is invisible to the planner it was entered for.
        raise ValueError("%s wants a shelf life in days: it is what makes it rank as ageing"
                         % name)
    book = moves.bought if bought else moves.corrected
    return book(cx, name, grade=grade, quantity=measure(quantity, "the quantity"), unit=unit,
                  shelf_life_days=whole(shelf_life, "the shelf life", 0) if shelf_life else None,
                  acquired_on=date(one(query, "acquired_on"), "the date it came in"),
                  cause=cause)


# --- the settings ---------------------------------------------------------

def settings_page(cx, query: dict | None = None, problem: str | None = None) -> str:
    """The household's facts, each one saying where it came from.

    The source is shown on every figure because the day one of them starts
    arriving from the accountant is a change of source and not a migration
    (docs/fleet.md), and a board that showed only the number would make that
    day look like nothing had happened.
    """
    body = ["<h1>the settings</h1>", nav("/settings"), needs_answer(problem),
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
    return state(ORIGINS.get(source, source), marked=source == "agent")


def _number_row(cx, key, what, least):
    """One figure, its box and its source.

    The hidden `fields` input tells the handler this form carried the key at
    all: an untouched key and an emptied box are the same absence in a
    posted form, and writing the difference away would be the board quietly
    changing a setting nobody looked at.
    """
    return ("<input type='hidden' name='fields' value='%s'>"
            "<div class='row'>"
            "<label class='name' for='%s'>%s</label>"
            "<input id='%s' name='%s' type='number' inputmode='numeric' min='%s' value='%s'>"
            "%s</div>"
            % (h(key), h(key), h(what), h(key), h(key), h(least),
               h(settings.get(cx, key)), _origin(cx, key)))


def _days_row(cx, key, what):
    """A day list as seven boxes, because nobody should have to spell wednesday."""
    stored = settings.get(cx, key)
    try:
        chosen, unreadable = set(settings.days(stored)), ""
    except ValueError:
        # A day list the household cannot read is a week nobody scheduled, and
        # a page that raised over it would be the one page able to fix it.
        chosen = set()
        unreadable = "<p class='needs-answer'>%s is unreadable: %s</p>" % (h(key), h(stored))
    boxes = "".join(
        "<label><input type='checkbox' name='%s' value='%s'%s> %s</label> "
        % (h(key), h(day), " checked" if day in chosen else "", h(day))
        for day in settings.WEEK)
    return ("<input type='hidden' name='fields' value='%s'>"
            "<div class='row'><span class='name'>%s</span>%s</div>"
            "<div class='row'>%s</div>%s"
            % (h(key), h(what), _origin(cx, key), boxes, unreadable))


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
            % (h(rule["value"]), h(rule["kind"]), state(rule["note"] or ""),
               h(rule["kind"]), h(rule["value"])))
    filters = settings.recipe_filters(cx)
    sends = "the search sends diet %s, intolerances %s, and excludes %s" % (
        filters.diet or "nothing",
        ", ".join(filters.intolerances) or "nothing",
        ", ".join(filters.exclude_ingredients) or "nothing")
    kinds = "".join("<option value='%s'>%s</option>" % (h(kind), h(kind))
                    for kind in settings.KINDS)
    return ("<h2>what will not be eaten</h2>"
            + ("".join(rows) or "<p class='quiet'>nothing is ruled out.</p>")
            + "<p class='quiet'>%s</p>" % h(sends)
            + "<form method='post' action='/settings'><div class='row'>"
              "<input type='hidden' name='do' value='add-rule'>"
              "<label class='name'>what <input name='value' required></label>"
              "<label>as a <select name='kind'>%s</select></label>"
              "<label>note <input name='note' size='10'></label>"
              "<button class='primary' type='submit'>add it</button>"
              "</div></form>" % kinds)


def _kitchen(cx):
    """What the kitchen has.

    Absent and unlisted are not the same thing and the two buttons say so. A
    row reading `not here` drops a recipe: it is the household stating it does
    not own the thing. Forgetting the row says nothing either way and lets
    every recipe through again (kitchen/settings.py).
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
            % (h(kit["name"]),
               state("in the kitchen" if kit["present"] else "not here",
                      marked=not kit["present"]),
               h(kit["name"]), "" if kit["present"] else "yes",
               "say it is gone" if kit["present"] else "say it is here"))
    return ("<h2>the kitchen</h2>"
            + ("".join(rows) or "<p class='quiet'>nothing is written down, "
                                "so every recipe gets through.</p>")
            + "<form method='post' action='/settings'><div class='row'>"
              "<input type='hidden' name='do' value='set-equipment'>"
              "<input type='hidden' name='present' value='yes'>"
              "<label class='name'>what <input name='name' required></label>"
              "<button class='primary' type='submit'>add it</button>"
              "</div></form>")


def settings_edit(cx, query: dict) -> str:
    """One change to the household's facts, and then the settings as they stand."""
    try:
        doing = one(query, "do")
        if doing == "save":
            _save(cx, query)
        elif doing == "add-rule":
            value = one(query, "value")
            if not value:
                raise ValueError("a rule wants something to rule out")
            settings.add_dietary_rule(cx, one(query, "kind"), value,
                                      note=one(query, "note") or None)
        elif doing == "drop-rule":
            settings.remove_dietary_rule(cx, one(query, "kind"), one(query, "value"))
        elif doing == "set-equipment":
            name = one(query, "name")
            if not name:
                raise ValueError("a piece of kit wants a name")
            settings.add_equipment(cx, name, present=bool(one(query, "present")))
        elif doing == "drop-equipment":
            settings.remove_equipment(cx, one(query, "name"))
        else:
            raise ValueError("the settings cannot %r" % doing)
    except ValueError as bad:
        return settings_page(cx, query, problem=str(bad))
    return settings_page(cx, query)


def _save(cx, query: dict) -> None:
    """Write what changed, and only what changed.

    Saving every box would turn every default into a typed figure the first
    time anyone pressed save, and the board would lose the one thing the
    source column is for - saying which figures the household has actually
    decided.

    Everything is read and checked before anything is written: half a saved
    form is worse than a rejected one, because nothing says which half.
    """
    carried = set(many(query, "fields"))
    wanted = {}
    for key, what, least in NUMBERS:
        if key in carried:
            wanted[key] = str(whole(one(query, key), what, least))
    for key, _what in DAY_LISTS:
        if key in carried:
            wanted[key] = ",".join(settings.days(",".join(many(query, key))))
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

@dataclass(frozen=True)
class Awaiting:
    """One meal still owed an answer, in the four facts the question needs.

    Not planner.week.Meal: that one is a slot the planner is filling, and this
    one is a row the board is asking about. The recipe pointer is on neither.
    """
    id: int
    on: datetime.date
    slot: str
    servings: int | None
    kind: str


def to_confirm(cx, today: datetime.date | None = None) -> list["Awaiting"]:
    """The meals still owed a 'did you cook this', oldest first.

    The reading is `week.awaiting`'s; what the board supplies is the two
    policies above, which are its own.
    """
    today = today or datetime.date.today()
    if not week.planned(cx):
        return []
    return [Awaiting(row["id"], row["meal_on"], row["slot"], row["servings"], row["kind"])
            for row in week.awaiting(cx, behind_days=BEHIND_DAYS, limit=AWAITING,
                                     today=today)]


def confirm_page(cx, query: dict | None = None, problem: str | None = None,
       today: datetime.date | None = None) -> str:
    """The meals waiting on an answer, with the two buttons that give it.

    Answered standing in a kitchen, on a phone, so there is one question per
    row and two targets to hit. The row is marked as needing an answer in the
    one colour the board keeps for that.
    """
    today = today or datetime.date.today()
    meals = to_confirm(cx, today)
    body = ["<h1>the confirmations</h1>", nav("/confirm"), needs_answer(problem)]
    if meals:
        body.append("".join(_meal_row(meal, today) for meal in meals))
    elif week.planned(cx):
        body.append("<p class='quiet'>nothing is waiting on an answer.</p>")
    else:
        body.append("<p class='quiet'>the week is not planned yet, "
                    "so there is nothing to confirm.</p>")
    return shell("the confirmations", "".join(body))


def _meal_row(meal, today):
    """One meal, one question, two answers.

    A portion of an earlier cook is asked whether it was eaten, not whether it
    was cooked, because it was cooked on another day and the question would be
    about the wrong evening.

    There is no cause in this form. Everywhere else on the board one is minted
    per render, because correcting the same ingredient twice is two real
    edits; a meal is cooked once, ever, so planner/week.py keys it on the meal
    itself and a phone that sent the answer, lost the tailnet and sent it
    again moves the stock once.
    """
    when, behind = said(meal.on, today)
    for_how_many = " for %s" % meal.servings if meal.servings else ""
    eaten = meal.kind == week.LEFTOVERS
    return (
        "<div class='row'>"
        "<span class='name needs-answer'>%s%s<span class='quiet'> - %s%s</span></span>"
        "%s"
        "<form method='post' action='/confirm'>"
        "<input type='hidden' name='meal' value='%s'>"
        "<button class='primary' name='answer' value='cooked'>%s</button>"
        "<button name='answer' value='skipped'>did not</button>"
        "</form></div>"
        % (h(meal.slot), h(for_how_many), h(when),
           " - leftovers" if eaten else "", state(behind),
           h(meal.id), "ate it" if eaten else "cooked it"))


def confirm_answer(cx, query: dict) -> str:
    """One answer, handed to the plan, and then whatever is still waiting.

    Both answers are the planner's own functions rather than an update
    written here. Skipping a meal empties it and empties whatever was going to
    eat its second portion; confirming one moves the stock under
    'plan_meal:<id>' and knows a portion of an earlier cook moves none. A
    board that wrote those rules a second time would be a board that drifts
    from them.
    """
    try:
        answer = one(query, "answer")
        if answer not in ("cooked", "skipped"):
            raise ValueError("an answer is cooked or skipped, not %r" % answer)
        meal = whole(one(query, "meal"), "the meal")
        if answer == "cooked":
            return _cooked(cx, query, meal)
        # Both writers answer None for a meal that is not there to answer for,
        # and a form carrying a stale id is exactly how that happens. Said
        # plainly, in the colour the board keeps for being asked, rather than
        # rendered as though the answer had landed.
        if week.skip(cx, meal) is None:
            raise ValueError("there is no such meal to answer for")
    except ValueError as bad:
        return confirm_page(cx, query, problem=str(bad))
    return confirm_page(cx, query)


def _cooked(cx, query, meal_id):
    """Say a meal happened, and take what it used out of the pantry.

    The lines come from the stove and go straight to the planner. The plan
    holds a pointer and the recipe's lines are not ours to keep (docs/db.md),
    so they are fetched at the moment the answer is given, handed over to be
    matched against the household's own names, and dropped. Without that the
    button wrote `cooked_at` and moved nothing:
    the meal left both lists, nobody was ever asked again, and the pantry went
    on describing a kitchen with a kilo of chicken that had been eaten - the
    exact fiction the confirm loop exists to prevent (pm/backlog.md).

    A cook whose method could not be had is left unanswered and says so. A
    meal silently marked done is worse than one still being asked about, and
    the question is still a good one tomorrow.
    """
    row = week.meal(cx, meal_id)
    if row is not None and week.still_to_cook(row):
        method = STOVE.method(row["recipe_id"], usage=usage_into(cx))
        if not method.ok:
            return confirm_page(cx, query, problem="%s the meal is still waiting on an"
                                                   " answer." % method.sentence)
        _answered(week.confirm_cooked(cx, meal_id, lines=method.lines))
        return confirm_page(cx, query)
    # A portion of an earlier cook moves no stock of its own, and a cook with
    # no pointer left has nothing to fetch - a closed week, or a slot planned
    # when there was no key. Both are answered and neither is a subtraction.
    _answered(week.confirm_cooked(cx, meal_id))
    return confirm_page(cx, query)


def _answered(row):
    """The row a plan writer hands back, or the refusal a missing meal is owed.

    `confirm_cooked` and `skip` both answer None for a meal that is gone or
    was already struck out. A form carrying a stale id is how that happens,
    and a page rendered as though the answer had landed is the one outcome
    worth refusing: the meal stays on the list and nobody knows why.
    """
    if row is None:
        raise ValueError("there is no such meal to answer for")
    return row


# --- what board/serve.py wires -------------------------------------------

# The type is board/chrome.py's, as the shell and the escaping are. Every
# render takes (cx, query) and hands back a whole document.
ROUTES = (
    Route("/pantry", "GET", pantry_page),
    Route("/pantry", "POST", pantry_edit),
    Route("/settings", "GET", settings_page),
    Route("/settings", "POST", settings_edit),
    Route("/confirm", "GET", confirm_page),
    Route("/confirm", "POST", confirm_answer),
)
