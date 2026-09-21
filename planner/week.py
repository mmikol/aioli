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
"""
import datetime
from dataclasses import dataclass, field

from kitchen import moves, pantry, settings
from matching.ingredients import PantryItem, RecipeIngredient, alias_index, cover
from matching.units import Conversion
from recipes.client import MissingKey, QuotaExhausted, Spoonacular, SpoonacularError, usage_into

LUNCH, DINNER = "lunch", "dinner"
SLOTS = (LUNCH, DINNER)

COOK, LEFTOVERS = "cook", "leftovers"

DRAFT, LIVE, CLOSED, UNFILLED = "draft", "live", "closed", "unfilled"

DAYS = 7

# The ceiling, stated out loud because a planner is the easiest place in this
# repo to write something unbounded. How much of the host the stack may take
# is configuration and the host is not settled - it may be a 16 GB machine
# with a model running beside it - so the work here is bounded whatever the
# machine, and a machine with room is not a reason to write something that
# needs it (pm/backlog.md). One plan is:
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
# land in either order.
WEIGHTS = {"pantry": 1.0, "buying": 0.5}

# settings.cook_days and settings.shop_days are deliberately not read here.
# Grouping the week's cooking into the household's two sessions is its own
# item ("Neither cadence is scheduled"), and it constrains the shopping
# through shelf life as well, so a planner that half-honoured it would hand
# back a week with four dinners nobody is home to cook. What the cadence
# reaches into today is how long a dish may take, which is
# settings.max_ready_minutes for the day it is cooked on, and that is read
# below.


@dataclass(frozen=True)
class Candidate:
    """One dish the search offered, decided against this kitchen.

    `uses` is the household's own names for what it covers and `to_buy` is a
    count, so nothing the service authored survives the parse. The recipe id
    is a pointer and the only thing here that ever reaches a table.
    """
    recipe_id: int
    uses: tuple[str, ...] = ()
    to_buy: int = 0
    ready_limit: int | None = None
    found_by: str = "pantry"


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
class Week:
    """Seven days of lunch and dinner, and what the planner made of them."""
    period: str
    starts_on: datetime.date
    ends_on: datetime.date
    meals: tuple[Meal, ...] = ()
    note: str = ""
    score: float = 0.0
    terms: dict = field(default_factory=dict)

    @property
    def cooks(self):
        """The dishes, in the order they are cooked."""
        return tuple(meal for meal in self.meals if meal.kind == COOK)

    @property
    def empty(self):
        """True when nothing was chosen at all, which is a week to say so about."""
        return all(meal.recipe_id is None for meal in self.meals)

    @property
    def filled(self):
        """True when every slot the household left open has something in it."""
        return all(meal.skipped or meal.kind is not None for meal in self.meals)

    @property
    def to_buy(self):
        """How many of the week's lines the pantry cannot answer."""
        return sum(meal.to_buy for meal in self.cooks)


def period_of(day):
    """The ISO week a date falls in, which is how a run is keyed (001)."""
    year, week, _ = _as_date(day).isocalendar()
    return "%04d-W%02d" % (year, week)


def monday_of(day):
    """The Monday of the week a date falls in."""
    day = _as_date(day)
    return day - datetime.timedelta(days=day.weekday())


def next_monday(today=None):
    """The Monday the plan starts on.

    The planning run happens on a Saturday for a week that starts on Monday,
    so the default is the Monday ahead. A run on a Monday plans the day it is
    standing on rather than a week away, which is what someone asking for a
    plan on Monday morning means.
    """
    today = _as_date(today or datetime.date.today())
    if today.weekday() == 0:
        return today
    return monday_of(today) + datetime.timedelta(days=DAYS)


def terms(candidate, urgency):
    """The objective, term by term, for one dish against what is left of the pantry.

    `urgency` is what each pantry name is still worth: a name an earlier dish
    already claimed is worth nothing, so two dishes cannot both be paid for
    consuming the same spinach.
    """
    return {
        "pantry": sum(urgency.get(name, 0.0) for name in candidate.uses),
        "buying": -float(candidate.to_buy),
    }


def score(candidate, urgency, weights=None):
    """One number for a dish. Higher is a better week."""
    weights = WEIGHTS if weights is None else weights
    return sum(weights.get(name, 0.0) * value
               for name, value in terms(candidate, urgency).items())


def plan(cx, client=None, *, start=None, today=None, skipped=(), pool=POOL):
    """Plan the week beginning on `start`, from the pantry outward.

    `skipped` is the slots the household has struck out, as (date, slot)
    pairs; they are left empty and nothing is cooked for them.

    A week that cannot be looked up comes back as a week that says so: no key,
    no points left, or a service that cannot be reached all return a plan
    whose slots are empty and whose note names the reason. Half a week is
    worse than an honest one (pm/backlog.md), and an exception here would
    leave the run with nothing to write down at all.
    """
    today = _as_date(today or datetime.date.today())
    start = _as_date(start or next_monday(today))
    days = [start + datetime.timedelta(days=n) for n in range(DAYS)]
    servings = settings.household_size(cx)
    struck = {(_as_date(day), slot) for day, slot in skipped}

    kinds, eats = pairing(days, struck)
    caps_by_day = {day: settings.max_ready_minutes(cx, day) for day in days}
    caps = sorted({caps_by_day[day] for (day, _), how in kinds.items() if how == COOK})
    if not caps:
        return _bare(days, struck,
                     "every meal this week is marked skipped, so there is nothing to plan")

    try:
        if client is None:
            client = Spoonacular(usage=usage_into(cx))
        candidates = _candidates(cx, client, caps, servings, today, pool)
    except SpoonacularError as refusal:
        return _bare(days, struck, _why(refusal))
    if not candidates:
        return _bare(days, struck, "nothing came back that this kitchen can cook")

    return _assemble(cx, days, struck, kinds, eats, candidates, caps_by_day, servings, today)


def save(cx, week, run_id=None, state=None):
    """Write a week down: one plan row and fourteen meals, or neither.

    A week nothing could be found for is saved too, in the 'unfilled' state,
    because a row saying plainly that the week could not be planned is worth
    more on the board than a missing one.
    """
    state = state or (UNFILLED if week.empty else DRAFT)
    with cx.transaction():
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


def read(cx, plan_id):
    """A plan and its meals, in the order the week happens in."""
    row = cx.execute("select * from plan where id = %s", (plan_id,)).fetchone()
    if row is None:
        return None
    meals = cx.execute(
        "select * from plan_meal where plan_id = %s"
        " order by meal_on, case slot when 'lunch' then 0 else 1 end", (plan_id,)).fetchall()
    return {"plan": row, "meals": meals}


def for_period(cx, period, state=None):
    """The newest plan for a period, or the newest in a given state."""
    if state is None:
        return cx.execute("select * from plan where period = %s"
                          " order by created_at desc, id desc limit 1", (period,)).fetchone()
    return cx.execute("select * from plan where period = %s and state = %s"
                      " order by created_at desc, id desc limit 1", (period, state)).fetchone()


def skip(cx, meal_id, note=None):
    """Mark a meal skipped, which is to say leave it empty.

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


def close(cx, plan_id):
    """Close a period and purge its recipe pointers. Returns how many went.

    This is the promise in docs/db.md kept as code rather than as prose: the
    id was a pointer so the board could re-fetch a meal while the plan was
    live, and the moment the plan is not live it is deleted. A closed week
    shows what it consumed, not what it was called.
    """
    with cx.transaction():
        purged = cx.execute(
            "update plan_meal set recipe_id = null"
            " where plan_id = %s and recipe_id is not null", (plan_id,)).rowcount
        cx.execute("update plan set state = %s, closed_at = now() where id = %s",
                   (CLOSED, plan_id))
        return purged


def confirm_cooked(cx, meal_id, ingredients=(), method=None):
    """Say a planned meal happened, and move the stock it used.

    The cause is 'plan_meal:<id>', which is the idempotency key the ledger
    takes at most once, so a confirmation tapped twice on a phone cooks the
    meal once (kitchen/moves.py).

    `ingredients` is handed in by whoever is holding the fetched method,
    because the planner never had them to keep. A portion of an earlier cook
    moves no stock at all - it went when the dish was cooked - so confirming
    one only stamps the row.
    """
    row = cx.execute("select * from plan_meal where id = %s", (meal_id,)).fetchone()
    if row is None or row["skipped"]:
        return None
    if row["kind"] == COOK and ingredients:
        moves.cook(cx, ingredients, eaten_on=row["meal_on"], slot=row["slot"],
                   method=method, cause="plan_meal:%d" % meal_id)
    return cx.execute(
        "update plan_meal set cooked_at = coalesce(cooked_at, now()) where id = %s returning *",
        (meal_id,)).fetchone()


def pairing(days, struck):
    """Which slots are cooks and which eat an earlier cook's second portion.

    Every dish is cooked once and eaten twice, so the week's open slots are
    walked in order and each one either starts a dish or finishes one. A
    dinner is always a cook: it is the meal the week is built around, and a
    dinner that were a portion of the night before would be the same dinner
    twice running. A lunch is the previous dinner's second portion where there
    is one, and a batch of its own where there is not, which is the settled
    decision in two lines.

    The edges of the week cannot pair and are not pretended to: the first
    lunch has no dinner before it inside the plan and the last dinner has no
    lunch after it, so each is cooked for one sitting. Replanning from a
    partial week is what would know about last Sunday, and it is its own item.
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
    ready = [cook for cook, left in spare.items()
             if left and 0 <= (day - cook[0]).days <= LEFTOVERS_GAP_DAYS]
    if not ready:
        return None
    # The previous day's dinner first, because that is the pairing a household
    # recognises without being told; a lunch batch only where there is no
    # dinner to follow. Nearest in time wins between equals.
    ready.sort(key=lambda cook: (cook[1] != DINNER, (day - cook[0]).days))
    return ready[0]


def _assemble(cx, days, struck, kinds, eats, candidates, caps_by_day, servings, today):
    """Put a dish on every cook, then lay the week out in order.

    The cooks are walked in the order the week happens in, and each one takes
    the best dish still standing against what is left of the pantry. Greedy on
    purpose: a sweep with a known ceiling rather than a solver turned loose.
    """
    urgency = _urgency(cx, today)
    most = max(caps_by_day[day] for (day, _), how in kinds.items() if how == COOK)
    # `summed` is not seeded with the term names on purpose: a term added
    # later lands in it by being returned from `terms`, and nothing here has
    # to be told about it.
    chosen, taken, total, summed = {}, set(), 0.0, {}
    for key in sorted((cook for cook, how in kinds.items() if how == COOK),
                      key=lambda cook: (cook[0], SLOTS.index(cook[1]))):
        cap = caps_by_day[key[0]]
        fits = [each for each in candidates if _fits(each, cap, most)]
        fresh = [each for each in fits if each.recipe_id not in taken]
        # A dish comes round again only when the pool is spent, because an
        # empty Thursday is worse than a repeat and the cooldown that would
        # rule on repeats reads the household's eating history, which is its
        # own item (docs/db.md).
        fits = fresh or fits
        if not fits:
            continue
        best = max(fits, key=lambda each: (score(each, urgency), -each.to_buy, -each.recipe_id))
        chosen[key] = best
        taken.add(best.recipe_id)
        for name, value in terms(best, urgency).items():
            summed[name] = summed.get(name, 0.0) + value
        total += score(best, urgency)
        for name in best.uses:
            urgency[name] = 0.0

    claimed = set(eats.values())
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

    note = "the week is planned: %d dishes cooked, %d meals from an earlier cook" % (
        len(position), len(claimed & set(position)))
    if blank:
        note += "; %d slots could not be filled" % blank
    return Week(period_of(days[0]), days[0], days[-1], tuple(meals), note, total, summed)


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
    """The reason a week holds nothing, in words a person can act on."""
    if isinstance(refusal, MissingKey):
        return "there is no Spoonacular key, so no dish could be looked up"
    if isinstance(refusal, QuotaExhausted):
        return "the day's Spoonacular points are spent, so no dish could be looked up"
    return "the recipe service could not be reached: %s" % refusal


def _candidates(cx, client, caps, servings, today, pool):
    """The dishes to choose from: the pantry pass, then the use-it-up pass.

    The first pass is complexSearch with what is in stock and fillIngredients
    on, once per distinct ready-time cap, because a search cannot filter two
    time limits at once and a Saturday afternoon is not a Tuesday evening. The
    second is findByIngredients over what turns soonest, which is the call for
    a week that has to use something up before it goes.

    `min_servings` is two sittings' worth: a dish that cannot yield that
    cannot be cooked once and eaten twice. Scaling a four-serving recipe down
    to a household of one is its own item and is not attempted here.
    """
    filters = settings.recipe_filters(cx)
    urgent = [row["ingredient"] for row in pantry.turning_soonest(
        cx, within_days=URGENT_WITHIN_DAYS, limit=SEARCH_INGREDIENTS, today=today)]
    include = _search_terms(urgent, pantry.ingredient_names(cx))
    held, aliases, conversions = _pantry_items(cx), _aliases(cx), _conversions(cx)

    found = []
    for cap in caps:
        payload = client.complex_search(
            include_ingredients=include,
            exclude_ingredients=filters["exclude_ingredients"],
            diet=filters["diet"], intolerances=filters["intolerances"],
            max_ready_time=cap, min_servings=servings * 2, number=PER_SEARCH)
        found.extend(_read_results(cx, _results(payload), cap, "pantry",
                                   held, aliases, conversions))
    if urgent:
        payload = client.find_by_ingredients(urgent, number=PER_SEARCH)
        found.extend(_read_results(cx, _results(payload), None, "turning",
                                   held, aliases, conversions))
    return _deduplicate(found, pool)


def _read_results(cx, results, cap, found_by, held, aliases, conversions):
    """Search results decided against this kitchen, and reduced to our own words.

    The wordings go into the matcher and no further: what survives this
    function is the household's own ingredient names, two counts and an id.
    """
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("id"), int):
            continue
        if settings.missing_equipment(cx, _equipment(result)):
            # A recipe wanting a pan this kitchen does not own is fiction that
            # reads as a perfectly good suggestion.
            continue
        coverage = cover(_needs(result), held, aliases=aliases, conversions=conversions)
        uses = tuple(sorted({need.ingredient for need in coverage.covered if need.ingredient}))
        # An uncertain line counts as something to buy until somebody answers
        # it. That is the direction that does not plan a week against a
        # kitchen nobody has (matching/ingredients.py).
        to_buy = len(coverage.missing) + len(coverage.uncertain)
        yield Candidate(result["id"], uses, to_buy, cap, found_by)


def _needs(result):
    """A search result's ingredient lines, as the matcher wants them.

    Both used and missed: which of them the pantry actually answers is this
    house's arithmetic to do, not the service's to be believed about.
    """
    lines = list(result.get("usedIngredients") or []) + list(result.get("missedIngredients") or [])
    return [RecipeIngredient(wording=str(line.get("original") or line.get("name") or ""),
                             quantity=line.get("amount"), unit=line.get("unit"))
            for line in lines if isinstance(line, dict)]


def _equipment(result):
    """What a result says it needs from the kitchen, where it says anything.

    A search result names no equipment, so this is usually empty and nothing
    is dropped. It reads the fuller payload's steps because that is the one
    the board already holds when it is showing a method, and a filter added
    under a working planner is a week of suggestions thrown away.
    """
    names = []
    for block in result.get("analyzedInstructions") or []:
        for step in (block or {}).get("steps") or []:
            for tool in (step or {}).get("equipment") or []:
                name = str((tool or {}).get("name") or "").strip()
                if name and name not in names:
                    names.append(name)
    return names


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


def _urgency(cx, today):
    """What each pantry name is worth to the week, highest for what turns soonest.

    A staple and a fresh perishable are both worth one; a thing turning today
    is worth URGENT_WEIGHT. This is the whole of "weighted towards what turns
    soonest", and it is a weight rather than a rule so that a week is never
    forced into a bad dish by one ageing lemon.
    """
    weights = {row["ingredient"]: 1.0 for row in pantry.in_stock(cx)}
    for row in pantry.turning_soonest(cx, within_days=URGENT_WITHIN_DAYS, today=today):
        left = max(int(row["days_left"]), 0)
        share = (URGENT_WITHIN_DAYS - left) / URGENT_WITHIN_DAYS
        weights[row["ingredient"]] = 1.0 + (URGENT_WEIGHT - 1.0) * share
    return weights


def _search_terms(urgent, stocked):
    """What goes out as includeIngredients: what turns soonest, then the rest.

    Capped, because the search is a query string and the pantry is not
    bounded. What is left off is not lost - it still scores through `cover`
    when the answers come back - it simply does not get to steer the search.
    """
    terms = list(urgent)
    for name in stocked:
        if name not in terms:
            terms.append(name)
    return terms[:SEARCH_INGREDIENTS]


def _pantry_items(cx):
    """The pantry as the matcher wants it: names, amounts and grades."""
    return [PantryItem(row["ingredient"],
                       None if row["quantity"] is None else float(row["quantity"]),
                       row["unit"], row["grade"], row["level"])
            for row in pantry.in_stock(cx)]


def _aliases(cx):
    """What the household has already said a wording means."""
    return alias_index(cx.execute(
        "select wording_key, ingredient, confirmed from ingredient_alias").fetchall())


def _conversions(cx):
    """The factors only the household or the ingredient can supply."""
    return [Conversion(row["from_unit"], row["to_unit"], float(row["factor"]),
                       row["ingredient"], row["source"])
            for row in cx.execute("select * from unit_conversion").fetchall()]


def _results(payload):
    """The recipes out of an answer, whichever shape the call returns them in.

    Cut to PER_SEARCH on the way in rather than trusted to arrive that way:
    `number` is a request and the ceiling above is a promise, and the promise
    should not depend on the service keeping to what it was asked for.
    """
    if isinstance(payload, list):
        return payload[:PER_SEARCH]
    if isinstance(payload, dict):
        found = payload.get("results")
        return found[:PER_SEARCH] if isinstance(found, list) else []
    return []


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
