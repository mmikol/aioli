"""The week: seven days of lunch and dinner, built from what is already in the house.

The pantry leads the plan. The search goes out with what is in stock and
favours what turns soonest, and what comes back is scored on how much of the
pantry it consumes and how little it has to be bought for - one objective
function, two terms, and a third is an addition rather than a reshaping
(pm/backlog.md).

Every dish is cooked once and eaten twice. A slot is therefore filled either
by a cook or by a portion of an earlier cook, and `kind` on the row says
which: a lunch is the previous dinner's second portion where there is one and
a batch of its own where there is not. The meals the household marked skipped
are left empty, and so is a slot nothing was found for - an empty Tuesday is
an honest answer and a missing Tuesday is not.

Nothing the service authored is kept. A recipe reaches the database as an
integer id on a live plan row and as nothing else; `close` purges it when the
period ends (docs/db.md). The words that pass through here - a recipe's
ingredient wordings, on their way into the matcher - are held for the length
of a call and written nowhere.

`pantry_items`, `aliases` and `conversions` are how anything else reads the
kitchen for the matcher. The planner owns the reads of matching's two tables
because it is the module that has to ask them together; matching itself takes
rows and stays free of the database, and a second spelling of these three
queries is how the week that was planned and the week that is shopped for
start disagreeing about the same pantry.
"""
import datetime
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from db.psql import Row
from kitchen import moves, one_of, pantry, settings
from kitchen.moves import DINNER, LUNCH, SLOTS
from matching.ingredients import (
    Alias,
    PantryItem,
    RecipeIngredient,
    alias_index,
    cover,
    normalise_name,
)
from matching.units import Conversion, convert, normalise_unit
from recipes import steps
from recipes.client import (
    NO_KEY,
    QUOTA,
    REFUSED,
    Spoonacular,
    SpoonacularError,
    results_of,
    trouble_of,
    usage_into,
)

# The two slots are kitchen/moves.py's, because they end up in its
# `eating_history.slot` column. Named here as well so the planner reads as
# the planner and the dependency runs the one way it already runs.

COOK, LEFTOVERS = "cook", "leftovers"

# Which pass a dish came back from. The pantry pass filters on a ready time
# and on a yield; the use-it-up pass filters on neither and answers neither,
# so both facts have to follow the candidate to the day it is placed on.
PANTRY, TURNING = "pantry", "turning"

DRAFT, LIVE, CLOSED, UNFILLED = "draft", "live", "closed", "unfilled"
STATES = (DRAFT, LIVE, CLOSED, UNFILLED)

# A week being eaten is in neither of these. A 'closed' week has had its
# pointers purged and its questions are long past; an 'unfilled' one is the
# planner saying plainly it could not plan, so there is nothing in it to
# confirm. A draft is in: it is a week in the making, and a board that stayed
# silent about one would look exactly like a board with nothing to ask.
NOT_BEING_EATEN = (CLOSED, UNFILLED)

# One plan to a period, the way the board's week view already reads it: the
# live one, and the newest draft where no plan is live yet. 003-the-week.sql
# permits a superseded draft beside the live one and `save` writes a fresh
# draft on every run, so a second planning run for one week would otherwise
# offer every dinner twice, with nothing on the two rows to tell them apart.
# Answering both moves the stock twice: the cause is 'plan_meal:<id>' and the
# two rows have different ids, so the ledger's idempotency cannot catch it.
_ONE_PLAN_A_PERIOD = (
    "select distinct on (period) id, period from plan where state <> all (%s)"
    " order by period, (state = 'live') desc, created_at desc, id desc")

DAYS = 7

# The ceiling, stated out loud because a planner is the easiest place in this
# repo to write something unbounded. How much of the host the stack may take
# is configuration and the host is not settled - it may be a 16 GB machine
# with a model running beside it - so the work here is bounded whatever the
# machine (pm/backlog.md). One plan is:
#
#   at most three calls out - one search per distinct ready-time cap, of which
#                             the household has two, and one use-it-up pass
#   at most POOL candidates - each a handful of strings and two numbers
#   at most one sweep       - every cook scored against every candidate once,
#                             which is under three hundred comparisons
#
# Nothing recurses, nothing backtracks, and no set here grows with the size of
# the pantry: the ingredient list sent to the search is capped as well,
# because a query naming sixty things is both a worse search and a string
# nobody bounded.
PER_SEARCH = 12
POOL = 36
SEARCH_INGREDIENTS = 12

# How far ahead a perishable counts as turning. Past a week it is stock like
# any other, and weighting it would be weighting the whole pantry.
URGENT_WITHIN_DAYS = 7

# What a thing turning today is worth against a thing that is merely in the
# house. Two rather than ten: the pantry term should lean towards what is
# ageing, not plan a week of dinners around one bag of spinach.
URGENT_WEIGHT = 2.0

# How long a second portion may wait. One day, which is a dinner feeding the
# next day's lunch and a lunch batch feeding the lunch after it. Anything
# longer is a keeps-well judgement, and nothing here is equipped to make one
# yet (pm/backlog.md, "Not everything reheats").
LEFTOVERS_GAP_DAYS = 1

# What a cook at the edge of the week is: a dish with nowhere to put its
# second portion. Said on the row rather than hidden, because it is the one
# place the week knowingly cooks for one.
ONE_SITTING = "cooked for one sitting: nothing in the week follows it"

# The objective. Exactly two terms in the MVP: how much of the pantry the week
# consumes, weighted towards what turns soonest, and how little it must be
# bought for.
#
# The shape is the point. `terms` returns one named number per term and
# `score` weighs them, so cost arrives as one more entry in each - "cost", the
# negative of what the basket comes to - and nothing that calls `score`
# changes. Prices are deferred; this seam is not (pm/backlog.md). A weight for
# a term that does not exist yet is simply not applied, so the two halves may
# land in either order. The basket the buying term reads is the one a cost
# term wants, and it is threaded through `terms` for that reason: a price
# charged per dish would bill every ingredient two dishes share twice.
WEIGHTS = {"pantry": 1.0, "buying": 0.5}

# settings.cook_days and settings.shop_days are deliberately not read here.
# Grouping the week's cooking into the household's two sessions is its own
# item ("Neither cadence is scheduled"), and it constrains the shopping
# through shelf life as well, so a planner that half-honoured it would hand
# back a week with four dinners nobody is home to cook. What the cadence
# reaches into today is how long a dish may take: settings.max_ready_minutes
# for the day it is cooked on, read below.


@dataclass(frozen=True)
class Candidate:
    """One dish the search offered, decided against this kitchen.

    `uses` and `buy` are both the household's own names - what the pantry
    answers and what it does not - so nothing the service authored survives
    the parse. The recipe id is a pointer and the only thing here that ever
    reaches a table.

    `buy` carries names rather than a count because a count cannot be shared
    between two dishes and a name can: a week that buys one lemon for two
    dinners is the overlap the planner is rewarded for (pm/backlog.md), and a
    count leaves the objective unable to see the basket.

    `servings` is what the dish yields where the search says. The pantry pass
    filters on it and the use-it-up pass neither filters nor answers, so an
    unknown yield is what `_feeds_twice` reads.
    """
    recipe_id: int
    uses: tuple[str, ...] = ()
    buy: tuple[str, ...] = ()
    ready_limit: int | None = None
    found_by: str = PANTRY
    servings: int | None = None

    @property
    def to_buy(self) -> int:
        """How many of this dish's lines the pantry cannot answer."""
        return len(self.buy)


@dataclass(frozen=True)
class Meal:
    """One slot of the week, filled or honestly empty.

    `eats` is the position in `Week.meals` of the cook this portion comes
    from, which `save` turns into `plan_meal.pairs_with`. A cook carries the
    recipe pointer; the portion that follows it does not, and reads the same
    id through the pairing.
    """
    day: datetime.date
    slot: str
    servings: int = 0
    kind: str | None = None
    recipe_id: int | None = None
    eats: int | None = None
    skipped: bool = False
    uses: tuple[str, ...] = ()
    to_buy: int = 0
    note: str | None = None


@dataclass(frozen=True)
class Plan:
    """A saved week as the database holds it: the plan row and its meals.

    Not `Week`, which is what the planner made before anything was written
    down. This is what `read` answers with, and the two are different enough
    that sharing a name would be the worse confusion.
    """
    row: Row
    meals: list[Row]


@dataclass(frozen=True)
class Week:
    """Seven days of lunch and dinner, and what the planner made of them."""
    period: str
    starts_on: datetime.date
    ends_on: datetime.date
    meals: tuple[Meal, ...] = ()
    note: str = ""
    score: float = 0.0
    terms: dict[str, float] = field(default_factory=dict)

    @property
    def cooks(self) -> tuple[Meal, ...]:
        """The dishes, in the order they are cooked."""
        return tuple(meal for meal in self.meals if meal.kind == COOK)

    @property
    def empty(self) -> bool:
        """True when nothing was chosen at all."""
        return all(meal.recipe_id is None for meal in self.meals)

    @property
    def filled(self) -> bool:
        """True when every slot the household left open has something in it."""
        return all(meal.skipped or meal.kind is not None for meal in self.meals)

    @property
    def to_buy(self) -> int:
        """How many of the week's lines the pantry cannot answer."""
        return sum(meal.to_buy for meal in self.cooks)


def period_of(day: datetime.date) -> str:
    """The ISO week a date falls in, which is how a run is keyed (001)."""
    year, week, _ = _as_date(day).isocalendar()
    return "%04d-W%02d" % (year, week)


def monday_of(day: datetime.date) -> datetime.date:
    """The Monday of the week a date falls in."""
    day = _as_date(day)
    return day - datetime.timedelta(days=day.weekday())


def next_monday(*, today: datetime.date | None = None) -> datetime.date:
    """The Monday the plan starts on.

    The planning run happens on a Saturday for a week that starts on Monday,
    so the default is the Monday ahead. A run on a Monday plans the day it is
    standing on rather than a week away.
    """
    today = _as_date(today or datetime.date.today())
    if today.weekday() == 0:
        return today
    return monday_of(today) + datetime.timedelta(days=DAYS)


def terms(candidate: Candidate, urgency: dict[str, float], *,
          basket: Iterable[str] = ()) -> dict[str, float]:
    """The objective, term by term, for one dish against what is left of the pantry.

    `urgency` is what each pantry name is still worth: a name an earlier dish
    already claimed is worth nothing, so two dishes cannot both be paid for
    consuming the same spinach.

    `basket` is what the week is already carrying home. A line another dish
    has already put on the list is a line this one costs nothing for, so the
    term charges what the week is not already buying and the dish that shares
    a lemon wins against the dish that wants a lemon of its own.
    """
    return {
        "pantry": sum(urgency.get(name, 0.0) for name in candidate.uses),
        "buying": -float(sum(1 for name in candidate.buy if name not in basket)),
    }


def score(candidate: Candidate, urgency: dict[str, float], *,
          weights: dict[str, float] | None = None, basket: Iterable[str] = ()) -> float:
    """One number for a dish. Higher is a better week."""
    weights = WEIGHTS if weights is None else weights
    return sum(weights.get(name, 0.0) * value
               for name, value in terms(candidate, urgency, basket=basket).items())


def plan(cx, client: Spoonacular | None = None, *, start: datetime.date | None = None,
         today: datetime.date | None = None,
         skipped: Iterable[tuple[datetime.date, str]] = (), pool: int = POOL) -> Week:
    """Plan the week beginning on `start`, from the pantry outward.

    `skipped` is the slots the household has struck out, as (date, slot)
    pairs; they are left empty and nothing is cooked for them.

    A week that cannot be planned comes back as a week that says so. No key,
    no points left, a service that cannot be reached, and a household figure
    that will not read as a number all return a plan whose slots are empty and
    whose note names the reason. Half a week is worse than an honest one
    (pm/backlog.md), and an exception here would leave the run with nothing to
    write down at all.
    """
    today = _as_date(today or datetime.date.today())
    start = _as_date(start or next_monday(today=today))
    days = [start + datetime.timedelta(days=n) for n in range(DAYS)]
    struck = {(_as_date(day), slot) for day, slot in skipped}
    kinds, eats = pairing(days, struck)

    try:
        servings = settings.household_size(cx)
        caps_by_day = {day: settings.max_ready_minutes(cx, day) for day in days}
    except ValueError as unreadable:
        # A setting that will not read as a number is a week nobody can plan,
        # and the message already names the key and what it holds. Guarded
        # here rather than around the whole body, because a ValueError out of
        # the search below would be a fault and not an answer.
        return _bare(days, struck, str(unreadable))
    caps = sorted({caps_by_day[day] for (day, _), how in kinds.items() if how == COOK})
    if not caps:
        return _bare(days, struck,
                     "every meal this week is marked skipped, so there is nothing to plan")

    try:
        if client is None:
            client = Spoonacular(usage=usage_into(cx))
        candidates, aside = _candidates(cx, client, caps, servings, today, pool)
    except SpoonacularError as refusal:
        return _bare(days, struck, _why(refusal))
    if not candidates:
        return _bare(days, struck, "nothing came back that this kitchen can cook")

    planned = _assemble(cx, days, struck, kinds, eats, candidates,
                        caps_by_day, servings, today)
    return planned if not aside else replace(planned, note="%s; %s" % (planned.note, aside))


def save(cx, week: Week, *, run_id: int | None = None, state: str | None = None) -> Row:
    """Write a week down: one plan row and fourteen meals, or neither.

    A week nothing could be found for is saved too, in the 'unfilled' state,
    because a row saying plainly that the week could not be planned is worth
    more on the board than a missing one.

    Writing a week also closes the weeks that are over and purges their
    recipe pointers, in the same transaction: the purge belongs on a clock
    and the clock does not exist yet, so it rides the two things that do
    happen (see `close_passed`).

    Raises ValueError when a portion points at no cook, or when `state` is not
    one of the four the column allows - both are weeks the planner should not
    have built, and the transaction takes the half-written plan with it.
    """
    state = one_of(state or (UNFILLED if week.empty else DRAFT), STATES, "plan state")
    with cx.transaction():
        # Every week planned closes the weeks that are over. The purge belongs
        # on a clock and the clock is the scheduler, which is an item below
        # this one (pm/backlog.md); until it exists, a promise with no caller
        # is a promise nobody keeps, and the pointers pile up a week at a time
        # on plans whose period ended a month ago (docs/db.md).
        close_passed(cx, today=week.starts_on)
        row = cx.execute(
            "insert into plan (period, starts_on, ends_on, state, run_id, note)"
            " values (%s, %s, %s, %s, %s, %s) returning *",
            (week.period, week.starts_on, week.ends_on, state, run_id, week.note)).fetchone()
        # The cooks go in first: a portion points at the cook it comes from,
        # so the cook needs an id before the pointer can be written.
        ids = {}
        for index, meal in enumerate(week.meals):
            if meal.kind != LEFTOVERS:
                ids[index] = _insert(cx, row["id"], meal)["id"]
        for meal in week.meals:
            if meal.kind != LEFTOVERS:
                continue
            if meal.eats not in ids:
                raise ValueError("a portion on %s points at no cook" % meal.day)
            _insert(cx, row["id"], meal, pairs_with=ids[meal.eats])
        return row


def read(cx, plan_id: int) -> Plan | None:
    """A plan and its meals, or None when there is no such plan."""
    row = cx.execute("select * from plan where id = %s", (plan_id,)).fetchone()
    if row is None:
        return None
    meals = cx.execute(
        "select * from plan_meal where plan_id = %s"
        " order by meal_on, array_position(%s::text[], slot)",
        (plan_id, list(SLOTS))).fetchall()
    return Plan(row, meals)


def migrated(cx) -> bool:
    """Whether there are plan tables to ask at all.

    `plan_meal` is the one asked for, because it is the table every reader
    here goes on to query: a database holding `plan` and not `plan_meal`
    passes a guard written against `plan` and then raises on the next
    statement.

    Asked rather than assumed, because a board against a database nobody has
    migrated yet should say the week is not planned and stay usable rather
    than fall over on the page a phone opens first.
    """
    return cx.execute("select to_regclass('plan_meal') as found").fetchone()["found"] is not None


def planned(cx) -> bool:
    """Whether there is a week to be asked about at all: a plan that is not
    closed and was not left unfilled."""
    if not migrated(cx):
        return False
    return cx.execute("select 1 from plan where state <> all (%s) limit 1",
                      (list(NOT_BEING_EATEN),)).fetchone() is not None


def awaiting(cx, *, behind_days: int, limit: int,
             today: datetime.date | None = None) -> list[Row]:
    """The meals still owed a 'did you cook this', oldest first.

    What is asked about is what is already behind: `today` and the
    `behind_days` before it, because the standing assumption is that an
    unconfirmed meal did not happen (pm/backlog.md). How far back is worth
    asking and how many fit on a screen are the asking view's to decide, so
    both arrive as arguments (board/pages.py), named, as
    `kitchen.pantry.turning_soonest` takes its own window.

    A slot with no kind is not a question with a true answer, so it is left
    out.
    """
    today = today or datetime.date.today()
    # The concatenation is _ONE_PLAN_A_PERIOD, a constant above; the dates,
    # the slots and the limit are all parameters.
    return cx.execute(
        "select meal.id, meal.meal_on, meal.slot, meal.servings, meal.kind"   # nosec B608
        " from plan_meal meal join (" + _ONE_PLAN_A_PERIOD + ") plan on plan.id = meal.plan_id"
        " where meal.meal_on between %s and %s and meal.kind is not null"
        " and not meal.skipped and meal.cooked_at is null"
        " order by meal.meal_on, array_position(%s::text[], meal.slot), meal.id"
        " limit %s",
        (list(NOT_BEING_EATEN), today - datetime.timedelta(days=behind_days), today,
         list(SLOTS), limit)).fetchall()


def still_to_cook(meal: Row) -> bool:
    """Whether a meal is still something to shop for.

    A portion of an earlier cook buys nothing: its ingredients went into the
    pan the day before. A skipped meal buys nothing either, and neither does
    one already cooked - the stock for it has moved. Replanning a week that
    went wrong is its own item; leaving a cooked dinner off the shopping is
    not replanning, it is not buying dinner twice.
    """
    return (meal["kind"] == COOK and meal["recipe_id"] is not None
            and not meal["skipped"] and meal["cooked_at"] is None)


def meal(cx, meal_id: int) -> Row | None:
    """One meal of a plan, or None when there is no such meal.

    Here rather than in whoever is asking, because every other read of
    `plan_meal` is here and two spellings of one select is how the board and
    the planner start disagreeing about a row (board/pages.py).
    """
    return cx.execute("select * from plan_meal where id = %s", (meal_id,)).fetchone()


def for_period(cx, period: str, *, state: str | None = None) -> Row | None:
    """The newest plan for a period, or the newest in a given state."""
    if state is None:
        return cx.execute("select * from plan where period = %s"
                          " order by created_at desc, id desc limit 1", (period,)).fetchone()
    return cx.execute("select * from plan where period = %s and state = %s"
                      " order by created_at desc, id desc limit 1", (period, state)).fetchone()


def skip(cx, meal_id: int, *, note: str | None = None) -> Row | None:
    """Mark a meal skipped, which is to say leave it empty. Returns the row,
    or None when there is no such meal.

    Skipping clears what was planned rather than hiding it, because a skipped
    meal that still held a dish would be a plan the pantry could be moved for
    (003-the-week.sql says the same thing as a constraint). Whatever was going
    to eat this cook's second portion is emptied too: there is nothing left
    for it to be a portion of.
    """
    with cx.transaction():
        cx.execute(
            "update plan_meal set kind = null, pairs_with = null, servings = 0,"
            " recipe_id = null, note = %s where pairs_with = %s",
            ("the cook it came from was skipped", meal_id))
        return cx.execute(
            "update plan_meal set skipped = true, kind = null, pairs_with = null,"
            " servings = 0, recipe_id = null, note = %s where id = %s returning *",
            (note or "the household marked this skipped", meal_id)).fetchone()


def close(cx, plan_id: int) -> int:
    """Close a period and purge its recipe pointers. Returns how many went.

    This is the promise in docs/db.md kept as code: the id was a pointer so
    the board could re-fetch a meal while the plan was live, and the moment
    the plan is not live it is deleted. A closed week shows what it consumed,
    not what it was called.
    """
    with cx.transaction():
        purged = cx.execute(
            "update plan_meal set recipe_id = null"
            " where plan_id = %s and recipe_id is not null", (plan_id,)).rowcount
        cx.execute("update plan set state = %s, closed_at = now() where id = %s",
                   (CLOSED, plan_id))
        return purged


def close_passed(cx, *, today: datetime.date | None = None) -> int:
    """Close every plan whose period has ended. Returns how many pointers went.

    docs/db.md permits the recipe id on a live row and promises it is purged
    when the period closes. Nothing was closing anything: the scheduler that
    would do it on a clock is an after-MVP item, so the purge rides the two
    things that do happen today - a week being planned above, and the board
    starting (board/serve.py). A month of use would otherwise leave eight
    pointers a week on weeks that ended weeks ago, all of them still readable
    by anybody who kept the link.

    A week still being eaten is not touched, and neither is one already
    closed: `ends_on` behind today is the whole test, and it is the
    household's today rather than the database's.
    """
    today = _as_date(today or datetime.date.today())
    with cx.transaction():
        purged = cx.execute(
            "update plan_meal set recipe_id = null where recipe_id is not null"
            " and plan_id in (select id from plan where ends_on < %s and state <> %s)",
            (today, CLOSED)).rowcount
        cx.execute("update plan set state = %s, closed_at = now()"
                   " where ends_on < %s and state <> %s", (CLOSED, today, CLOSED))
        return purged


def confirm_cooked(cx, meal_id: int, *, lines: Iterable[RecipeIngredient] = (),
                   method: str | None = None) -> Row | None:
    """Say a planned meal happened, and move the stock it used.

    Returns the meal row, or None when the meal is gone or was struck out -
    both of which a form carrying a stale id will ask about.

    The cause is 'plan_meal:<id>', which is the idempotency key the ledger
    takes at most once, so a confirmation tapped twice on a phone cooks the
    meal once (kitchen/moves.py).

    `lines` is the fetched recipe's own wordings, handed in by whoever is
    holding them because the planner never had them to keep (docs/db.md).
    Matching them against the household's names is `used_by` below, here
    rather than in the view that fetched them: it is the same arithmetic the
    grocery list does and it belongs beside the tables it writes.
    A portion of an earlier cook moves no stock at all - it went when the dish
    was cooked - so confirming one only stamps the row.
    """
    row = meal(cx, meal_id)
    if row is None or row["skipped"]:
        return None
    ingredients = used_by(cx, lines) if lines else ()
    if row["kind"] == COOK and ingredients:
        moves.cook(cx, ingredients, eaten_on=row["meal_on"], slot=row["slot"],
                   method=method, cause="%s%d" % (moves.MEAL, meal_id))
    return cx.execute(
        "update plan_meal set cooked_at = coalesce(cooked_at, now()) where id = %s returning *",
        (meal_id,)).fetchone()


def used_by(cx, lines: Iterable[RecipeIngredient]) -> list[moves.Used]:
    """What a cook took out of the cupboard, in the household's own names.

    Only what `cover` settled is handed over. A line nobody has confirmed the
    meaning of is a question the pantry page answers, and subtracting it
    quietly is how the pantry starts describing a kitchen nobody has
    (matching/ingredients.py). What is left unsubtracted stays on the shelf,
    which is the direction a person notices and corrects.
    """
    held, known, factors = for_matcher(cx)
    coverage = cover(lines, held, aliases=known, conversions=factors)
    shelved = {item.ingredient: item.unit for item in held}
    return [_taken(need, shelved.get(need.ingredient), factors)
            for need in coverage.covered if need.ingredient]


def _taken(need, shelf_unit, conversions) -> moves.Used:
    """One line as the ledger takes it, in the unit the shelf is measured in.

    `cover` answers in the recipe's unit because the recipe is what has to be
    satisfied, and `kitchen.pantry.subtract` refuses a unit that is not the
    shelf's rather than assuming a factor. So the amount comes back into the
    shelf's unit here, where the household's own conversions are already in
    hand. A line that will not convert goes over without an amount: the move
    is still recorded and the drift shows in the ledger, which is better than
    a confident wrong number in the pantry (kitchen/pantry.py).
    """
    line = moves.Used(need.ingredient, need.quantity, need.unit)
    if need.quantity is None or shelf_unit is None or need.unit is None:
        return line
    if normalise_unit(shelf_unit) == normalise_unit(need.unit):
        return replace(line, unit=shelf_unit)
    moved = convert(need.quantity, need.unit, shelf_unit,
                    ingredient=need.ingredient, conversions=conversions)
    if not moved:
        return replace(line, quantity=None, unit=None)
    return replace(line, quantity=moved.quantity, unit=shelf_unit)


def for_matcher(cx) -> tuple[list[PantryItem], dict[str, Alias], list[Conversion]]:
    """The pantry, the answered wordings and the factors, as the matcher wants them.

    The three readers below, asked together, because every caller wants all
    three: the plan, the grocery list and a confirmation all have to be
    looking at the same pantry.
    """
    return pantry_items(cx), aliases(cx), conversions(cx)


def pairing(days: Iterable[datetime.date],
            struck: set[tuple[datetime.date, str]]) -> tuple[dict, dict]:
    """Which slots are cooks and which eat an earlier cook's second portion.

    Every dish is cooked once and eaten twice, so the week's open slots are
    walked in order and each one either starts a dish or finishes one. A
    dinner is always a cook: it is the meal the week is built around, and a
    dinner that were a portion of the night before would be the same dinner
    twice running. A lunch is the previous dinner's second portion where there
    is one, and a batch of its own where there is not.

    The edges of the week cannot pair and are not pretended to: the first
    lunch has no dinner before it inside the plan and the last dinner has no
    lunch after it, so each is cooked for one sitting. Replanning from a
    partial week would know about last Sunday, and that is its own item.
    """
    kinds, eats, spare = {}, {}, {}
    for day in days:
        for slot in SLOTS:
            key = (day, slot)
            if key in struck:
                continue
            source = _spare_for(key, spare) if slot == LUNCH else None
            if source is None:
                kinds[key] = COOK
                spare[key] = True
            else:
                kinds[key] = LEFTOVERS
                eats[key] = source
                spare[source] = False
    return kinds, eats


def _spare_for(key, spare):
    """The cook whose second portion this slot eats, or None to cook instead."""
    day = key[0]
    # A day after the cook at the earliest: `spare` only holds cooks the walk
    # has already passed, and a lunch is filled before its own day's dinner
    # exists. The lower bound says that rather than guarding against a
    # same-day pairing that the order of the walk already rules out.
    ready = [cook for cook, left in spare.items()
             if left and 1 <= (day - cook[0]).days <= LEFTOVERS_GAP_DAYS]
    if not ready:
        return None
    # The previous day's dinner first, because that is the pairing a household
    # recognises without being told; a lunch batch only where there is no
    # dinner to follow. Nearest in time wins between equals.
    ready.sort(key=lambda cook: (cook[1] != DINNER, (day - cook[0]).days))
    return ready[0]


def _assemble(cx, days, struck, kinds, eats, candidates, caps_by_day, servings, today):
    """Put a dish on every cook, then lay the week out in order.

    Two jobs and two functions: choosing is a sweep over candidates and laying
    out is a walk over dates, and neither wants the other's accumulators in
    scope.
    """
    claimed = set(eats.values())
    chosen, total, summed = _choose(kinds, candidates, caps_by_day, servings, claimed,
                                    _urgency(cx, today))
    meals, position, blank = _lay_out(days, struck, kinds, eats, chosen, servings, claimed)

    note = "the week is planned: %d dishes cooked, %d meals from an earlier cook" % (
        len(position), len(claimed & set(position)))
    if blank:
        note += "; %d slots could not be filled" % blank
    return Week(period_of(days[0]), days[0], days[-1], tuple(meals), note, total, summed)


def _choose(kinds, candidates, caps_by_day, servings, claimed, urgency):
    """A dish on every cook, and what the week scored for them.

    The cooks are walked in the order the week happens in, and each one takes
    the best dish still standing against what is left of the pantry. Greedy on
    purpose: a sweep with a known ceiling rather than a solver turned loose.

    `summed` is not seeded with the term names: a term added to `terms` later
    lands in it by being returned. `basket` is the week's own accumulator
    beside `urgency` - one says what the pantry has left to give and the other
    says what the list already carries.
    """
    most = max(caps_by_day[day] for (day, _), how in kinds.items() if how == COOK)
    chosen, taken, total, summed, basket = {}, set(), 0.0, {}, set()
    for key in sorted((cook for cook, how in kinds.items() if how == COOK),
                      key=lambda cook: (cook[0], SLOTS.index(cook[1]))):
        cap = caps_by_day[key[0]]
        possible = [each for each in candidates
                    if _fits(each, cap, most)
                    and (key not in claimed or _feeds_twice(each, servings))]
        # A dish comes round again only when the pool is spent: an empty
        # Thursday is worse than a repeat, and the cooldown that would rule on
        # repeats reads the household's eating history - its own item
        # (docs/db.md).
        choices = [each for each in possible if each.recipe_id not in taken] or possible
        if not choices:
            continue
        best = max(choices, key=lambda each: (score(each, urgency, basket=basket),
                                              -each.to_buy, -each.recipe_id))
        best_score = score(best, urgency, basket=basket)
        chosen[key] = best
        taken.add(best.recipe_id)
        for name, value in terms(best, urgency, basket=basket).items():
            summed[name] = summed.get(name, 0.0) + value
        total += best_score
        for name in best.uses:
            urgency[name] = 0.0
        basket.update(best.buy)
    return chosen, total, summed


def _lay_out(days, struck, kinds, eats, chosen, servings, claimed):
    """The week as fourteen slots in the order they happen in.

    Also what could not be filled, and where each cook landed: a portion
    points at the cook it eats by position, and `save` turns that into a row
    id once the cook has one.
    """
    meals, position, blank = [], {}, 0
    for day in days:
        for slot in SLOTS:
            key = (day, slot)
            if key in struck:
                meals.append(Meal(day, slot, skipped=True,
                                  note="the household marked this skipped"))
                continue
            if kinds.get(key) == COOK:
                pick = chosen.get(key)
                if pick is None:
                    blank += 1
                    meals.append(Meal(day, slot,
                                      note="nothing that came back fits this day"))
                    continue
                position[key] = len(meals)
                meals.append(Meal(
                    day, slot, servings=servings, kind=COOK, recipe_id=pick.recipe_id,
                    uses=pick.uses, to_buy=pick.to_buy,
                    note=None if key in claimed else ONE_SITTING))
                continue
            source = eats.get(key)
            if source not in position:
                blank += 1
                meals.append(Meal(day, slot, note="the cook it would come from has no dish"))
                continue
            meals.append(Meal(day, slot, servings=servings, kind=LEFTOVERS,
                              eats=position[source]))
    return meals, position, blank


def _bare(days, struck, note):
    """The week as fourteen empty slots, and a note saying why.

    Not a half-week and not an exception: the shape of the week is still worth
    showing, and the reason it holds nothing is the only useful thing to say
    about it.
    """
    meals = tuple(
        Meal(day, slot, skipped=(day, slot) in struck,
             note="the household marked this skipped" if (day, slot) in struck else None)
        for day in days for slot in SLOTS)
    return Week(period_of(days[0]), days[0], days[-1], meals, note)


def _why(refusal):
    """The reason a week holds nothing, in words a person can act on.

    Which failure it was is recipes/client.py's to say; what to say about it
    is this module's. A service that answered 404 is not a service that could
    not be reached, and a note that said so sent somebody to look at their
    network.
    """
    trouble = trouble_of(refusal)
    if trouble == NO_KEY:
        return "there is no Spoonacular key, so no dish could be looked up"
    if trouble == QUOTA:
        return "the day's Spoonacular points are spent, so no dish could be looked up"
    if trouble == REFUSED:
        return "the recipe service answered %s, so no dish could be looked up" % refusal.status
    # Without the exception's own text: it already reads "could not be
    # reached" and carries the path it was reaching. The traceback board/
    # serve.py prints is where that belongs.
    return "the recipe service could not be reached"


def _candidates(cx, client, caps, servings, today, pool):
    """The dishes to choose from, and what to say about a search that refused.

    The first pass is complexSearch with what is in stock and fillIngredients
    on, once per distinct ready-time cap, because a search cannot filter two
    time limits at once and a Saturday afternoon is not a Tuesday evening. The
    second is findByIngredients over what turns soonest, for a week that has
    to use something up before it goes.

    `min_servings` is two sittings' worth: a dish that cannot yield that
    cannot be cooked once and eaten twice. Scaling a four-serving recipe down
    to a household of one is its own item and is not attempted here.

    Each call out is guarded on its own. A refusal on one of them - a 402 on
    the last pass, a blip on the network - used to throw away every dish the
    calls before it had already returned, along with the points they cost, and
    hand back a week saying no dish could be looked up while two dozen sat in
    hand. So a failure is collected and the week carries on with what it has;
    only a pass that leaves nothing at all raises, and then the week says why.
    """
    filters = settings.recipe_filters(cx)
    urgent = _distinct(row["ingredient"] for row in pantry.turning_soonest(
        cx, within_days=URGENT_WITHIN_DAYS, limit=SEARCH_INGREDIENTS, today=today))
    include = _include_ingredients(urgent, pantry.ingredient_names(cx))
    held, known, factors = for_matcher(cx)

    found, refusals = [], []
    for cap in caps:
        try:
            payload = client.complex_search(
                include_ingredients=include,
                exclude_ingredients=filters.exclude_ingredients,
                diet=filters.diet, intolerances=filters.intolerances,
                max_ready_time=cap, min_servings=servings * 2, number=PER_SEARCH)
        except SpoonacularError as refusal:
            refusals.append(refusal)
            continue
        found.extend(_read_results(cx, _results(payload), cap, PANTRY,
                                   held, known, factors))
    if urgent:
        try:
            payload = client.find_by_ingredients(urgent, number=PER_SEARCH)
        except SpoonacularError as refusal:
            refusals.append(refusal)
        else:
            found.extend(_read_results(cx, _results(payload), None, TURNING,
                                       held, known, factors))
    if not found and refusals:
        raise refusals[0]
    return _deduplicate(found, pool), _aside(refusals)


def _aside(refusals):
    """What a planned week says about a search that would not answer.

    The searches that did answer are dishes enough to cook a week from, and
    the points they cost are spent whatever happens next, so a refusal comes
    back as a sentence on the note. The week was narrower for it and the
    person reading the board is owed that much.
    """
    if not refusals:
        return ""
    return ("one of the searches was refused, so there was less to choose from - %s"
            % _why(refusals[0]))


def _distinct(names):
    """One entry per name, in the order they arrive.

    `turning_soonest` answers one row per lot and a search term is one word
    per thing, so three lots of chicken are one term rather than three of the
    twelve the query is capped at. Compared lowercased, the way
    `pantry.ingredient_names` groups them.
    """
    found, seen = [], set()
    for name in names:
        key = name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            found.append(name)
    return found


def _read_results(cx, results, cap, found_by, held, known, factors):
    """Search results decided against this kitchen, and reduced to our own words.

    The wordings go into the matcher and no further: what survives this
    function is the household's own ingredient names, two counts and an id.
    """
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("id"), int):
            continue
        if settings.missing_equipment(cx, steps.equipment_of(result)):
            # A recipe wanting a pan this kitchen does not own is fiction that
            # reads as a perfectly good suggestion.
            continue
        coverage = cover(steps.lines_of(result), held, aliases=known, conversions=factors)
        uses = tuple(sorted({need.ingredient for need in coverage.covered if need.ingredient}))
        yield Candidate(result["id"], uses, _buying(coverage), cap, found_by,
                        steps.whole_number(result.get("servings")))


def _buying(coverage):
    """What a dish would have to be bought for, by name and without repeats.

    An uncertain line counts as something to buy until somebody answers it.
    That is the direction that does not plan a week against a kitchen nobody
    has (matching/ingredients.py).

    The household's own name where `cover` settled one, the wording reduced to
    the thing itself where it did not - the same reduction the grocery list
    names a line by, so the planner is buying against the list a person will
    actually carry, and neither keeps a word the service authored.
    """
    names = []
    for need in tuple(coverage.missing) + tuple(coverage.uncertain):
        name = need.ingredient or normalise_name(need.wording) or need.wording.strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _deduplicate(found, pool):
    """One entry per recipe, keeping the tightest ready time it was found under.

    The same dish comes back from the weeknight search and the weekend one;
    the weeknight answer is the useful one, because it fits both days.
    """
    best = {}
    for candidate in found:
        held = best.get(candidate.recipe_id)
        if held is None or _rank(candidate) < _rank(held):
            best[candidate.recipe_id] = candidate
    return tuple(list(best.values())[:pool])


def _rank(candidate):
    """A ready-time cap as a sortable number; an unknown one sorts last."""
    return float("inf") if candidate.ready_limit is None else float(candidate.ready_limit)


def _fits(candidate, cap, most):
    """Whether a dish may be cooked on a day with this much time.

    findByIngredients takes no time filter, so how long its answers take is
    not known. One of those goes on a day the household has the most time and
    nowhere else, where a long cook cannot wreck the evening.
    """
    if candidate.ready_limit is None:
        return cap >= most
    return candidate.ready_limit <= cap


def _feeds_twice(candidate, servings):
    """Whether a dish may be cooked for a sitting that another meal follows.

    complexSearch is asked for `min_servings` of two sittings' worth, so a
    dish from the pantry pass yields them or it would not be here.
    findByIngredients takes no such filter and returns no yield at all, so a
    dish from the use-it-up pass gets the treatment its unknown ready time
    gets: it goes where nothing follows it. Promising a second helping off a
    dish that serves one is a lunch nobody can eat, and the schema says the
    batch is the cook's servings plus the portion's (003-the-week.sql).
    """
    if candidate.servings is not None:
        return candidate.servings >= servings * 2
    return candidate.found_by == PANTRY


def _urgency(cx, today):
    """What each pantry name is worth to the week, highest for what turns soonest.

    A staple and a fresh perishable are both worth one; a thing turning today
    is worth URGENT_WEIGHT. This is the whole of "weighted towards what turns
    soonest", and it is a weight rather than a rule so that a week is never
    forced into a bad dish by one ageing lemon.

    The weight is per name and the rows are per lot, so the lots are taken at
    their highest rather than in the order they arrive. The rows come back
    with the furthest-off last, so assigning would let a replacement bought
    today bury the lot that turns today - the one signal the whole term exists
    to carry, erased by the act of buying more.
    """
    weights = {row["ingredient"]: 1.0 for row in pantry.in_stock(cx)}
    for row in pantry.turning_soonest(cx, within_days=URGENT_WITHIN_DAYS, today=today):
        left = max(int(row["days_left"]), 0)
        share = (URGENT_WITHIN_DAYS - left) / URGENT_WITHIN_DAYS
        name = row["ingredient"]
        weights[name] = max(weights.get(name, 1.0), 1.0 + (URGENT_WEIGHT - 1.0) * share)
    return weights


def _include_ingredients(urgent, stocked):
    """What goes out as includeIngredients: what turns soonest, then the rest.

    Capped, because the search is a query string and the pantry is not
    bounded. What is left off is not lost - it still scores through `cover`
    when the answers come back - it simply does not get to steer the search.
    """
    names = list(urgent)
    for name in stocked:
        if name not in names:
            names.append(name)
    return names[:SEARCH_INGREDIENTS]


def pantry_items(cx) -> list[PantryItem]:
    """The pantry as the matcher wants it: names, amounts and grades."""
    return [PantryItem(row["ingredient"],
                       None if row["quantity"] is None else float(row["quantity"]),
                       row["unit"], row["grade"], row["level"])
            for row in pantry.in_stock(cx)]


def aliases(cx) -> dict[str, Alias]:
    """What the household has already said a wording means."""
    return alias_index(cx.execute(
        "select wording_key, ingredient, confirmed from ingredient_alias").fetchall())


def conversions(cx) -> list[Conversion]:
    """The factors only the household or the ingredient can supply."""
    return [Conversion(row["from_unit"], row["to_unit"], float(row["factor"]),
                       row["ingredient"], row["source"])
            for row in cx.execute("select * from unit_conversion").fetchall()]


def _results(payload):
    """The recipes out of an answer, cut to the ceiling this module promised.

    Which shape a call answers in is recipes/client.py's to know. What is
    this module's is PER_SEARCH: `number` is a request to the service and the
    ceiling above is a promise, so it is applied to what came back rather
    than trusted to have arrived that way.
    """
    return (results_of(payload) or [])[:PER_SEARCH]


def _insert(cx, plan_id, meal, pairs_with=None):
    """One meal row. The recipe id is the only thing here the service touched."""
    return cx.execute(
        "insert into plan_meal (plan_id, meal_on, slot, servings, kind, pairs_with,"
        " skipped, recipe_id, note) values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning *",
        (plan_id, meal.day, meal.slot, meal.servings, meal.kind, pairs_with,
         meal.skipped, meal.recipe_id, meal.note)).fetchone()


def _as_date(day):
    """A date from whatever a caller had to hand."""
    if isinstance(day, datetime.datetime):
        return day.date()
    return day
