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

The list's own page is not gated the same way: it is the page that goes to the
shop, and asking for it twice in an aisle is once too many. What holds it to
the same rule is the hour planner/groceries.py keeps a dish for - the first
reading pays for the week, and a reload, a pull-to-refresh or a tap back from
the week inside that hour costs nothing at all.

Nothing the service authored is stored by either view. What is shown is the
household's own: the plan's dates and slots, the pantry's names, and - where
a wording matched nothing in the house - that wording reduced to the thing
itself, held for the length of the render and written nowhere (docs/db.md).

The tests for both views sit at the foot of tests/planner/test_groceries.py,
beside the arithmetic they render: what this file is worth testing for is
that the list a person carries says what the planner computed, and splitting
the two apart would test the rendering against a fixture of itself.
"""
import datetime

from board.chrome import Route, h, nav, needs_answer, one, said, shell, state
from planner import groceries, week

# The board's shared words are board/chrome.py's and are imported, not written
# again. One escape function, one shell, one way a date is spoken: a second set
# of them is two boards inside a fortnight, and the first thing to go would be
# the escaping.

# Where the list is reached from. It is not in board/chrome.py's NAV because
# the nav is the four views a phone taps between, and this is the week's own
# list.
LIST_PATH = "/groceries"
WEEK_PATH = "/"

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


def week_page(cx, query: dict | None = None, problem: str | None = None,
       today: datetime.date | None = None) -> str:
    """The week as it stands, and the list beside it when it has been asked for."""
    today = today or datetime.date.today()
    query = query or {}
    showing, trouble = _showing(cx, query, today)
    body = ["<h1>the week</h1>", nav(WEEK_PATH), needs_answer(problem or trouble)]
    if showing is None:
        body.append("<p class='quiet'>no week is planned yet, so there is nothing to look at.</p>")
        return shell("the week", "".join(body))
    body.append(_when(showing.row, today))
    body.append(_table(showing, today))
    body.append(_beside(cx, showing, asked=bool(one(query, "list"))))
    return shell("the week", "".join(body))


def groceries_page(cx, query: dict | None = None, problem: str | None = None,
       today: datetime.date | None = None) -> str:
    """The list on its own: the page that goes to the shop.

    The week is one tap away rather than repeated above it: a list read in an
    aisle wants the whole screen, and the days are no use standing in front of
    the tomatoes.
    """
    today = today or datetime.date.today()
    query = query or {}
    showing, trouble = _showing(cx, query, today)
    body = ["<h1>the list</h1>", nav(LIST_PATH), needs_answer(problem or trouble),
            "<p class='quiet'><a href='%s'>the week this is for</a></p>" % h(WEEK_PATH)]
    if showing is None:
        body.append("<p class='quiet'>no week is planned yet, so there is nothing to buy.</p>")
        return shell("the list", "".join(body))
    body.append(_when(showing.row, today))
    body.append(_list(cx, showing))
    return shell("the list", "".join(body))


# --- which week is being looked at ---------------------------------------

def _showing(cx, query, today):
    """The week the board shows, and what to say about the asking.

    A plan can be asked for by id: a link from a mail carries one. Otherwise it
    is this period's live week, then whatever was last planned for this period,
    then the same two for the week ahead - what a Saturday evening wants, the
    planning run having just made next week.

    A `?plan=` that is not a number comes back as a sentence rather than as no
    week at all: a truncated link and an unplanned week look identical on a
    phone and only one of them is worth going to look for.
    """
    if not week.migrated(cx):
        return None, ""
    asked = one(query, "plan")
    if asked:
        try:
            plan_id = int(asked)
        except ValueError:
            return None, "a plan is asked for by number, not %r" % asked
        return week.read(cx, plan_id), ""
    for period in (week.period_of(today), week.period_of(week.next_monday(today=today))):
        for wanted in (week.LIVE, None):
            row = week.for_period(cx, period, state=wanted)
            if row is not None:
                return week.read(cx, row["id"]), ""
    return None, ""


def _when(plan, today):
    """Which week this is, and what the plan is currently worth.

    The state is shown because the four of them mean different things to the
    person reading: a draft is a proposal, a live week is the one being eaten,
    a closed one is history with its pointers gone, and an unfilled one is the
    planner saying plainly that it could not plan (003-the-week.sql).
    """
    when, behind = said(plan["starts_on"], today)
    states = {week.DRAFT: "a draft", week.LIVE: "the week in force",
              week.CLOSED: "closed",
              week.UNFILLED: "the planner could not fill this week"}
    return "<p class='quiet'>the week of %s - %s - %s</p>" % (
        h(when), h(behind), h(states.get(plan["state"], plan["state"])))


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
    for day in sorted(set(_days(showing.row)) | set(by_day)):
        slots = by_day.get(day, {})
        when, behind = said(day, today)
        rows.append("<tr><td>%s<span class='quiet'> - %s</span></td>%s%s</tr>" % (
            h(when), h(behind),
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
        return "<td class='quiet'>%s</td>" % h(NOTHING)
    if meal["skipped"]:
        return "<td class='quiet'>skipped</td>"
    if meal["kind"] == week.LEFTOVERS:
        return "<td>%s%s</td>" % (h(_from(meal, by_id)), _marks(meal))
    if meal["kind"] == week.COOK:
        served = " for %s" % meal["servings"] if meal["servings"] else ""
        return "<td>cooked%s%s%s</td>" % (h(served), _marks(meal), _note(meal))
    return "<td class='quiet'>%s%s</td>" % (h(NOTHING), _note(meal))


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
    return "<span class='quiet'> - %s</span>" % h(meal["note"]) if meal["note"] else ""


# --- the list -------------------------------------------------------------

def _beside(cx, showing, asked):
    """The list under the week, or what asking for it will cost.

    The cost is said in lookups rather than points because a lookup is the
    thing a person can picture: one per dish still to be cooked, and a dish
    the week cooks twice is looked up once.
    """
    if asked:
        return _list(cx, showing)
    dishes = {meal["recipe_id"] for meal in showing.meals if week.still_to_cook(meal)}
    if not dishes:
        return ("<h2>the list</h2><p class='quiet'>there is no dish left to shop for"
                " on this week.</p>")
    return ("<h2>the list</h2>"
            "<p class='quiet'>the list looks up each dish - %d %s against the day's"
            " points - so it is made when you ask for it.</p>"
            "<p><a class='button' href='%s'>make the list</a></p>"
            % (len(dishes), "lookup" if len(dishes) == 1 else "lookups",
               h("%s?list=1" % WEEK_PATH)))


def _list(cx, showing):
    """What to carry home, what to ask about, and what the house already has."""
    shopping = groceries.for_plan(cx, showing.row["id"])
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
    body = ["<h2>the list</h2>"]
    if shopping.note:
        body.append("<p class='quiet'>%s</p>" % h(shopping.note))
    if not shopping.dishes:
        # Nothing was looked up, so nothing is known. An empty list and a list
        # that could not be built look identical on a phone and mean opposite
        # things, so only one of them gets to say the house has everything.
        return "".join(body)
    if shopping.unknown:
        # A list can be complete in what it holds and short of half the week:
        # the dishes that were fetched may well be covered by the pantry while
        # the ones that refused are the seven dinners nobody is shopping for.
        # That is read off `unknown` and never off what is on the list.
        body.append("<p class='needs-answer'>this list is short of %d %s:"
                    " what they want is not on it.</p>"
                    % (len(shopping.unknown),
                       "meal" if len(shopping.unknown) == 1 else "meals"))
    elif shopping.empty:
        body.append("<p class='quiet'>nothing to buy: the week is cooked"
                    " from what is already in the house.</p>")
    if shopping.empty:
        return "".join(body)
    body.append(
        "<p class='quiet'>%d to buy, %d to ask about. %d of them more than one meal wants,"
        " %d bought <span class='soon'>%s</span>.</p>"
        % (len(shopping.buy), len(shopping.ask), len(shopping.shared),
           len(shopping.alone), h(ALONE)))
    return "".join(body)


def _aisles(shopping):
    """The list itself, one section per part of a shop."""
    body = []
    for aisle, lines in groceries.by_aisle(shopping.buy):
        body.append("<h2>%s</h2>" % h(aisle))
        body.extend(_line(line) for line in lines)
    return "".join(body)


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
              else "<span class='soon'> - %s</span>" % h(ALONE))
    return ("<div class='row'><span class='name'>%s%s</span>%s</div>"
            % (h(line.name), wanted, state(line.said)))


def _questions(shopping):
    """What nobody has said either way, as questions rather than assumptions.

    Each one is a wording that resembles something on the shelf without
    anybody having confirmed they are the same thing. Answering it means
    naming the thing in the pantry the way the recipe does, on the pantry
    page, so the next match is exact. Nothing writes an `ingredient_alias`
    row yet - `matching.ingredients.remember` is the shape one takes and has
    no caller - so the answer that would save a tap is still an item, and
    this page does not pretend otherwise.
    """
    body = ["<h2>what nobody has said</h2>",
            "<p class='quiet'>these stay questions until somebody answers them -"
            " naming the thing on <a href='/pantry'>the pantry</a> the way the recipe"
            " does is the answer.</p>"]
    for line in shopping.ask:
        body.append(
            "<div class='row'><span class='name needs-answer'>%s"
            "<span class='quiet'> - %s</span></span>%s</div>"
            % (h(line.name), h(line.reason), state(line.said, marked=True)))
    return "".join(body)


def _already(shopping):
    """What the house already holds, folded away.

    Worth showing and not worth scrolling past: this is the week built from
    the pantry outward - the promise the planner makes - and a list that never
    said so would look like a week planned from nothing.
    """
    lines = "".join(
        "<div class='row'><span class='name'>%s</span>%s</div>"
        % (h(line.name), state(line.said)) for line in shopping.held)
    return ("<h2>what the house already has</h2>"
            "<details><summary>%d already in the kitchen</summary>%s</details>"
            % (len(shopping.held), lines))


# --- what board/serve.py wires -------------------------------------------

# The type is board/chrome.py's. Every render takes (cx, query) and hands back
# a whole document, as in board/pages.py. The week answers on "/" and nowhere
# else: that is where the nav points it, and a page with two addresses is a
# page whose link a person cannot recognise.
ROUTES = (
    Route(WEEK_PATH, "GET", week_page),
    Route(LIST_PATH, "GET", groceries_page),
)
