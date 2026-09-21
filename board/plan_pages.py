"""The week and its list: the half of the board a person reads.

Two views. The week is the seven days and both slots, saying which meal is a
cook, which is the previous dinner's second serving, which was struck out and
which the planner could not fill - an empty Tuesday shown as an empty Tuesday,
because that is what the plan actually says. The list is what the week has to
be shopped for, grouped into the parts of a shop and carrying the two figures
that stand in for money until money arrives: what more than one meal wants,
and what is being bought for a single meal only.

The arithmetic is planner/groceries.py's and the plan is planner/week.py's.
Nothing here writes: a skip and a confirmation are both the confirmations
view's, which already hands them to the planner's own functions, and a second
page making the same writes in its own words is how the two would drift.

Why the list is asked for rather than always shown. Building it looks a dish
up per cook, and a page that spent quota on every reload would spend a day's
points on a phone left open on a counter (pm/backlog.md). So the week costs
nothing to look at and says plainly what asking will cost.

Nothing the service authored is stored by either view. What is shown is the
household's own: the plan's dates and slots, the pantry's names, and - where
a wording matched nothing in the house - that wording reduced to the thing
itself, held for the length of the render and written nowhere (docs/db.md).
"""
import collections
import datetime

from board.pages import _h, _nav, _one, _problem, _said, _state, shell
from planner import groceries, week

# The board's own helpers, above, are imported, not written again. One escape
# function, one shell, one way a date is spoken: a second set of them is two
# boards inside a fortnight, and the first thing to go would be the escaping.

# Where the list is reached from. It is not in board/pages.py's NAV because
# the nav is the four views a phone taps between, and this is the week's own
# list.
LIST = "/groceries"
WEEK = "/"

# What a slot says when there is nothing in it. A meal the household struck
# out and a meal the planner could not fill are different silences and the
# board says which: one is a decision and the other is a gap.
NOTHING = "nothing planned"

# The colour the stylesheet keeps for something about to turn, borrowed for
# the line that is bought for one meal only. It is the same warning - a thing
# nothing else in the week will finish is a thing heading for the bin.
ALONE = "for one meal only"

# How many days the table will walk, whatever a plan row says. A period is a
# week and the loop below is over dates rather than rows, so this stops a
# mistyped `ends_on` from turning one page into a year of empty days.
MOST_DAYS = 31

Showing = collections.namedtuple("Showing", "plan meals")


def week_page(cx, query=None, problem=None, today=None):
    """The week as it stands, and the list beside it when it has been asked for."""
    today = today or datetime.date.today()
    query = query or {}
    showing = _showing(cx, query, today)
    body = ["<h1>the week</h1>", _nav(WEEK), _problem(problem)]
    if showing is None:
        body.append("<p class='quiet'>no week is planned yet, so there is nothing to look at.</p>")
        return shell("the week", "".join(body))
    body.append(_when(showing.plan, today))
    body.append(_table(showing, today))
    body.append(_beside(cx, showing, asked=bool(_one(query, "list"))))
    return shell("the week", "".join(body))


def groceries_page(cx, query=None, problem=None, today=None):
    """The list on its own: the page that goes to the shop.

    The week is one tap away rather than repeated above it: a list read in an
    aisle wants the whole screen, and the days are no use standing in front of
    the tomatoes.
    """
    today = today or datetime.date.today()
    query = query or {}
    showing = _showing(cx, query, today)
    body = ["<h1>the list</h1>", _nav(LIST), _problem(problem),
            "<p class='quiet'><a href='%s'>the week this is for</a></p>" % _h(WEEK)]
    if showing is None:
        body.append("<p class='quiet'>no week is planned yet, so there is nothing to buy.</p>")
        return shell("the list", "".join(body))
    body.append(_when(showing.plan, today))
    body.append(_list(cx, showing))
    return shell("the list", "".join(body))


# --- which week is being looked at ---------------------------------------

def _showing(cx, query, today):
    """The week the board shows: the one in force, then the one coming.

    A plan can be asked for by id: a link from a mail carries one. Otherwise it
    is this period's live week, then whatever was last planned for this period,
    then the same two for the week ahead - what a Saturday evening wants, the
    planning run having just made next week.
    """
    if not _migrated(cx):
        return None
    asked = _one(query, "plan")
    if asked:
        try:
            return _read(cx, int(asked))
        except ValueError:
            return None
    for period in (week.period_of(today), week.period_of(week.next_monday(today))):
        for state in (week.LIVE, None):
            row = week.for_period(cx, period, state)
            if row is not None:
                return _read(cx, row["id"])
    return None


def _read(cx, plan_id):
    """One plan and its meals, as this file wants them."""
    held = week.read(cx, plan_id)
    return None if held is None else Showing(held["plan"], held["meals"])


def _migrated(cx):
    """Whether there is a plan table to ask at all.

    Asked rather than assumed, the way the confirmations view asks: a board
    against a database that has not been migrated yet should say the week is
    not planned and stay usable, not fall over on the page a phone opens first.
    """
    return cx.execute("select to_regclass('plan') as found").fetchone()["found"] is not None


def _when(plan, today):
    """Which week this is, and what the plan is currently worth.

    The state is shown because the four of them mean different things to the
    person reading: a draft is a proposal, a live week is the one being eaten,
    a closed one is history with its pointers gone, and an unfilled one is the
    planner saying plainly that it could not plan (003-the-week.sql).
    """
    when, behind = _said(plan["starts_on"], today)
    said = {"draft": "a draft", "live": "the week in force", "closed": "closed",
            "unfilled": "the planner could not fill this week"}
    return "<p class='quiet'>the week of %s - %s - %s</p>" % (
        _h(when), _h(behind), _h(said.get(plan["state"], plan["state"])))


# --- the seven days -------------------------------------------------------

def _table(showing, today):
    """The week: a row a day, a column a slot.

    A table rather than fourteen rows because the question asked of this page
    is what is happening on Thursday, and a column of dinners answers it at a
    glance where a list makes it a scroll.

    The days come from the period and not from the rows. The planner writes a
    row for every slot, empty ones included, but a week rendered only from
    what is in the table would hide the one failure worth seeing - a day that
    lost its rows - behind a page that looks perfectly reasonable.
    """
    by_id = {meal["id"]: meal for meal in showing.meals}
    by_day = {}
    for meal in showing.meals:
        by_day.setdefault(meal["meal_on"], {})[meal["slot"]] = meal
    rows = []
    for day in sorted(set(_days(showing.plan)) | set(by_day)):
        slots = by_day.get(day, {})
        when, behind = _said(day, today)
        rows.append("<tr><td>%s<span class='quiet'> - %s</span></td>%s%s</tr>" % (
            _h(when), _h(behind),
            _cell(slots.get("lunch"), by_id), _cell(slots.get("dinner"), by_id)))
    return ("<table><tr><th>day</th><th>lunch</th><th>dinner</th></tr>%s</table>"
            % "".join(rows))


def _days(plan):
    """The days the period covers, first to last."""
    days, day = [], plan["starts_on"]
    while day <= plan["ends_on"] and len(days) < MOST_DAYS:
        days.append(day)
        day += datetime.timedelta(days=1)
    return days


def _cell(meal, by_id):
    """One slot, in the words the plan itself uses.

    The recipe pointer is not rendered. The only thing it is for is fetching
    the method at the stove, the item after this one (docs/db.md).
    """
    if meal is None:
        return "<td class='quiet'>%s</td>" % _h(NOTHING)
    if meal["skipped"]:
        return "<td class='quiet'>skipped</td>"
    if meal["kind"] == week.LEFTOVERS:
        return "<td>%s%s</td>" % (_h(_from(meal, by_id)), _marks(meal))
    if meal["kind"] == week.COOK:
        served = " for %s" % meal["servings"] if meal["servings"] else ""
        return "<td>cooked%s%s%s</td>" % (_h(served), _marks(meal), _note(meal))
    return "<td class='quiet'>%s%s</td>" % (_h(NOTHING), _note(meal))


def _from(meal, by_id):
    """Which cook a second serving comes from, said as the day it was cooked."""
    source = by_id.get(meal["pairs_with"])
    if source is None:
        return "a second serving"
    return "the second serving of %s's %s" % (
        source["meal_on"].strftime("%A").lower(), source["slot"])


def _marks(meal):
    """Whether this one has been answered for: the confirmations set it."""
    return "<span class='quiet'> - cooked</span>" if meal["cooked_at"] else ""


def _note(meal):
    """The plan's own note on a slot: usually why it is the way it is."""
    return "<span class='quiet'> - %s</span>" % _h(meal["note"]) if meal["note"] else ""


# --- the list -------------------------------------------------------------

def _beside(cx, showing, asked):
    """The list under the week, or what asking for it will cost.

    The cost is said in lookups rather than points because a lookup is the
    thing a person can picture: one per dish still to be cooked, and a dish
    the week cooks twice is looked up once.
    """
    if asked:
        return _list(cx, showing)
    dishes = {meal["recipe_id"] for meal in showing.meals if groceries.still_to_cook(meal)}
    if not dishes:
        return ("<h2>the list</h2><p class='quiet'>there is no dish left to shop for"
                " on this week.</p>")
    return ("<h2>the list</h2>"
            "<p class='quiet'>the list looks up each dish - %d %s against the day's"
            " points - so it is made when you ask for it.</p>"
            "<p><a class='button' href='%s'>make the list</a></p>"
            % (len(dishes), "lookup" if len(dishes) == 1 else "lookups",
               _h("%s?list=1" % WEEK)))


def _list(cx, showing):
    """What to carry home, what to ask about, and what the house already has."""
    shopping = groceries.for_plan(cx, showing.plan["id"])
    if shopping is None:
        return "<p class='quiet'>this week could not be read.</p>"
    parts = [_summary(shopping)]
    if shopping.buy:
        parts.append(_aisles(shopping))
    if shopping.ask:
        parts.append(_questions(shopping))
    if shopping.held:
        parts.append(_already(shopping))
    return "".join(parts)


def _summary(shopping):
    """What the list came to, and the two figures that stand in for money.

    The overlap is the whole of the waste argument in the MVP: a thing bought
    for one meal and finished by another is a thing that does not turn in the
    fridge, and a line nothing else wants is where the bin starts. Said as
    counts rather than a percentage, because a person shops from counts.
    """
    said = ["<h2>the list</h2>"]
    if shopping.note:
        said.append("<p class='quiet'>%s</p>" % _h(shopping.note))
    if not shopping.dishes:
        # Nothing was looked up, so nothing is known. An empty list and a list
        # that could not be built look identical on a phone and mean opposite
        # things, so only one of them gets to say the house has everything.
        return "".join(said)
    if shopping.empty:
        said.append("<p class='quiet'>nothing to buy: the week is cooked"
                    " from what is already in the house.</p>")
        return "".join(said)
    said.append(
        "<p class='quiet'>%d to buy, %d to ask about. %d of them more than one meal wants,"
        " %d bought <span class='soon'>%s</span>.</p>"
        % (len(shopping.buy), len(shopping.ask), len(shopping.shared),
           len(shopping.alone), _h(ALONE)))
    return "".join(said)


def _aisles(shopping):
    """The list itself, one section per part of a shop."""
    said = []
    for aisle, lines in groceries.by_aisle(shopping.buy):
        said.append("<h2>%s</h2>" % _h(aisle))
        said.extend(_line(line) for line in lines)
    return "".join(said)


def _line(line):
    """One thing to buy: what it is, how much, and whether anything else wants it.

    A line no other meal wants is marked in the colour the board keeps for
    something about to turn, because that is what it is: bought whole, used
    once, and left to go off unless somebody cooks it again.

    The amount goes in the state and everything else in the name. The
    stylesheet holds the state on one line, which is right for "400 g" and
    wrong for a sentence, so a sentence goes where the column wraps.
    """
    wanted = ("<span class='quiet'> - %d meals</span>" % len(line.meals) if line.shared
              else "<span class='soon'> - %s</span>" % _h(ALONE))
    return ("<div class='row'><span class='name'>%s%s</span>%s</div>"
            % (_h(line.name), wanted, _state(line.said)))


def _questions(shopping):
    """What nobody has said either way, as questions rather than assumptions.

    Each one is a wording that resembles something on the shelf without
    anybody having confirmed they are the same thing. Answering it means
    correcting the pantry's own name for the thing, on the pantry page; a form
    here would be a second place that writes an alias, and the one that writes
    them is the matching layer's (matching/ingredients.py).
    """
    said = ["<h2>what nobody has said</h2>",
            "<p class='quiet'>these stay questions until somebody answers them -"
            " naming the thing on <a href='/pantry'>the pantry</a> the way the recipe"
            " does is the answer.</p>"]
    for line in shopping.ask:
        said.append(
            "<div class='row'><span class='name needs-answer'>%s"
            "<span class='quiet'> - %s</span></span>%s</div>"
            % (_h(line.name), _h(line.reason), _state(line.said, marked=True)))
    return "".join(said)


def _already(shopping):
    """What the house already holds, folded away.

    Worth showing and not worth scrolling past: this is the week built from
    the pantry outward - the promise the planner makes - and a list that never
    said so would look like a week planned from nothing.
    """
    lines = "".join(
        "<div class='row'><span class='name'>%s</span>%s</div>"
        % (_h(line.name), _state(line.said)) for line in shopping.held)
    return ("<h2>what the house already has</h2>"
            "<details><summary>%d already in the kitchen</summary>%s</details>"
            % (len(shopping.held), lines))


# --- what board/serve.py wires -------------------------------------------

Route = collections.namedtuple("Route", "path method render")

# Every render takes (cx, query) and hands back a whole document, as in
# board/pages.py. The week answers on "/" because that is where the nav points
# it; it answers on "/week" as well, for a router that already has something
# of its own on "/" - the same page under its own name rather than a second
# page to keep in step.
ROUTES = (
    Route(WEEK, "GET", week_page),
    Route("/week", "GET", week_page),
    Route(LIST, "GET", groceries_page),
)
