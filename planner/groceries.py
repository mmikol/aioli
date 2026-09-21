"""A plan is not a grocery list, so this makes one: what the week wants, less what the house has.

A plan row carries a recipe id and nothing else, which is the whole of what
may be kept (docs/db.md), so the list is computed and never stored: each
cook's dish is fetched once, run through the matcher, and dropped. That is
also why there is no `grocery_line` table under this - a row reading "2 cups
of invented lemon" would be the service's words in a table, and the line does
not bend for a convenience. The list is a function of the plan, the pantry
and one pass of lookups, so it can be built again at any time and nothing
goes stale in a table nobody purges.

Computed again, though, is not the same as fetched again. A list is read in an
aisle, pocketed and read again three shelves later, and a lookup per dish per
render would spend a day's points on a phone left on a counter. So the
lookups go through the hour the terms do allow (recipes/hold.py): held in
memory, bounded by age and by count, written nowhere.

Three answers rather than two, because matching/ingredients.py already models
them. What the house holds is not bought. What it plainly does not hold is
bought. What resembles something on the shelf without anybody having said so
is a question, and it stays a question: a silent yes leaves a dinner short on
Thursday and a silent no buys a second jar, and neither is discovered until
somebody is standing in the kitchen.

Waste is still the thing being minimised and it works without money: a thing
bought for Monday should be finished by Thursday, so every line says which
meals want it, and the list reports what the week managed to share against
what it is buying for one meal only. No prices, no stores, no packs and no
brands - those are the section below this one in the backlog, and the seams
they arrive through are the same ones: a line already carries a quantity for
a price to hang off and an aisle for a store to replace.

The pantry is spent as the week is walked rather than compared against eight
times over. Two dinners each wanting the 400 g in the fridge is one dinner
cooked and one shopped for, and a list that said otherwise would send the
household home short of exactly one dinner.
"""
from dataclasses import dataclass, field, replace

from kitchen import pantry
from matching.ingredients import PantryItem, RecipeIngredient, cover, normalise_name
from matching.units import convert, normalise_unit
from planner import week
from recipes.client import MissingKey, QuotaExhausted, Spoonacular, SpoonacularError, usage_into
from recipes.hold import Hold

# Where a line goes when nothing says which part of a shop it belongs in.
ELSEWHERE = "the rest"

# The ceiling, stated where the work is done, because a list over a week of
# meals is the second easiest place in this repo to write something unbounded.
#
#   at most one lookup per distinct dish - a week holds at most eight cooks,
#                                          and a dish repeated is fetched once
#   at most PER_RECIPE lines per dish    - cut on the way in rather than
#                                          trusted to arrive that way
#
# So the whole list is a few hundred short strings whatever the plan holds,
# and nothing here grows with the size of the pantry. How much of the host the
# stack may take is a setting and the host is not settled (pm/backlog.md), so
# this is sized for a week of dinners rather than for the machine it happens
# to run on.
MOST_LOOKUPS = 8
PER_RECIPE = 40

# What counts as the same amount, in the units the arithmetic lands in. Below
# this a line is short of nothing and the household is not sent out for it.
CRUMB = 1e-9

# One hold for the life of the process, in front of the lookups. The list is
# rebuilt on every render - a phone left on it in an aisle, a pull-to-refresh,
# a tap back and forth between the week and the list - and each render would
# otherwise spend a point per dish against a free tier of fifty a day. Six
# loads would take the whole day's quota, and the person it is taken from is
# whoever opens a meal at the stove that evening (pm/backlog.md).
#
# It holds the service's words, so it holds them the way recipes/steps.py
# does: the hour the terms allow, bounded by count as well, in memory and
# written nowhere (docs/db.md).
HELD = Hold()


@dataclass(frozen=True)
class Amount:
    """How much of a thing to carry home, in the unit the recipes asked in.

    The unit is the recipe's rather than the shelf's, because the recipe is
    what has to be satisfied and the shelf's pack size is the price book's
    business (pm/backlog.md). A count has no unit worth saying out loud: two
    lemons are two lemons and not two pieces of lemon.
    """
    quantity: float | None = None
    unit: str | None = None

    @property
    def said(self):
        """The amount as a person would write it on a list."""
        if self.quantity is None:
            return ""
        if self.unit is None or self.unit == "piece":
            return "%.4g" % self.quantity
        return "%.4g %s" % (self.quantity, self.unit)


@dataclass(frozen=True)
class Line:
    """One thing to buy, ask about, or find already in the cupboard.

    `meals` is the plan_meal ids that want it, which is the whole of the
    overlap arithmetic: a line more than one meal wants is a thing that will
    be finished, and a line one meal wants is a thing that may well go off.
    Nothing of the recipe is carried - the id is the household's own row.

    `amounts` is usually one entry. It is two when a week wants a can of
    something and 200 g of the same thing and nothing says what a can weighs:
    adding those would be inventing a number, and two honest amounts on one
    line is what a person can actually shop from.
    """
    name: str
    amounts: tuple[Amount, ...] = ()
    aisle: str = ELSEWHERE
    meals: tuple[int, ...] = ()
    reason: str = ""
    candidates: tuple[tuple[str, float], ...] = ()

    @property
    def shared(self):
        """True when more than one meal wants it."""
        return len(self.meals) > 1

    @property
    def said(self):
        """Every amount on the line, in words. Empty when the recipes gave none."""
        return " and ".join(amount.said for amount in self.amounts if amount.said)


@dataclass(frozen=True)
class Groceries:
    """The week's shopping, in the three answers the matcher gives.

    `buy` is what the house plainly does not have, `ask` is what nobody has
    confirmed either way, and `held` is what the pantry already answers and
    nobody has to carry. Keeping the third is not bookkeeping: it shows the
    household that the week was built around what was already in the house,
    which is the promise the whole planner makes.

    `unknown` is the meals whose dish could not be looked up - no key, no
    points, or a service that would not answer. They are named rather than
    quietly left out, because a list missing a dinner nobody mentioned is
    worse than no list at all.

    `dishes` is how many meals the list was actually built from, and it is
    what tells an empty list from one that could not be built. Both have
    nothing on them and they mean opposite things: one says the house has
    everything and the other says nobody knows.
    """
    buy: tuple[Line, ...] = ()
    ask: tuple[Line, ...] = ()
    held: tuple[Line, ...] = ()
    plan_id: int | None = None
    period: str = ""
    note: str = ""
    unknown: tuple[int, ...] = ()
    dishes: int = 0

    @property
    def shared(self):
        """What is bought for more than one meal."""
        return tuple(line for line in self.buy if line.shared)

    @property
    def alone(self):
        """What is bought for a single meal, which is where waste starts."""
        return tuple(line for line in self.buy if not line.shared)

    @property
    def overlap(self):
        """The share of the list more than one meal wants, from 0 to 1.

        Read over what is bought and not over what the house already holds:
        the question this answers is whether the week finishes what it sends
        somebody out for. A list with nothing on it is 0 and not a division.
        """
        return len(self.shared) / len(self.buy) if self.buy else 0.0

    @property
    def empty(self):
        """True when there is nothing to carry and nothing to answer."""
        return not self.buy and not self.ask


@dataclass(frozen=True)
class Wanted:
    """One meal's ingredient lines, as the service words them.

    Transient in the strongest sense: the wordings reach the matcher and the
    screen and nothing else (docs/db.md). `meal` is the plan_meal id, so a
    line can say which meals want it while carrying nothing of the dish.

    `aisles` maps a normalised wording to the part of a shop the service files
    it under. An aisle is a supermarket's vocabulary rather than a recipe's
    words - recipes/fixtures.py settles that in TAXONOMY_KEYS - and it is used
    to order a list on a screen and written down nowhere.
    """
    meal: int
    lines: tuple[RecipeIngredient, ...] = ()
    aisles: dict = field(default_factory=dict)


def for_plan(cx, plan_id, client=None):
    """The shopping for a saved plan, or None when there is no such plan.

    One lookup per distinct dish still to be cooked, and the answers are read
    against the pantry in the order the week happens in. A plan whose pointers
    have been purged, whose meals are all cooked or which holds no dish at all
    comes back as a list saying so rather than as an empty one: an empty list
    and a list that could not be built look identical on a phone, and only one
    of them means "you have everything".
    """
    plan = week.read(cx, plan_id)
    if plan is None:
        return None
    row = plan["plan"]
    bare = Groceries(plan_id=row["id"], period=row["period"])
    cooks = [meal for meal in plan["meals"] if still_to_cook(meal)]
    if not cooks:
        return replace(bare, note=_nothing_pointed_at(row, plan["meals"]))

    wanted, unknown, refusal = _look_up(cx, client, cooks)
    if not wanted:
        return replace(bare, unknown=unknown,
                       note=refusal or "no dish on this week could be looked up")
    items, aliases, conversions = _kitchen(cx)
    found = gather(wanted, items, aliases=aliases, conversions=conversions)
    return replace(found, plan_id=row["id"], period=row["period"], unknown=unknown,
                   note=_summary(len(wanted), unknown, refusal))


def gather(wanted, held, *, aliases=None, conversions=()):
    """The meals' lines against the pantry, folded into one list.

    `wanted` is the meals in the order the week happens in, and the order is
    load-bearing: the pantry is spent as it is walked, so the stock that fed
    Monday is not offered to Thursday as well. That is the same rule the
    planner scores by - two dishes cannot both be paid for one bag of spinach
    - kept here in the arithmetic the household actually shops from.

    No database and no network: every decision this makes is a function of its
    arguments, so the whole of it can be tested without either.
    """
    wanted = list(wanted)
    remaining = [dict(ingredient=item.ingredient, quantity=item.quantity, unit=item.unit,
                      grade=item.grade, level=item.level) for item in held]
    buy, ask, kept = {}, {}, {}
    for meal in wanted:
        items = [PantryItem(row["ingredient"], row["quantity"], row["unit"],
                            row["grade"], row["level"]) for row in remaining]
        coverage = cover(meal.lines, items, aliases=aliases, conversions=conversions)
        for need in coverage.covered:
            _fold(kept, _name(need), need, meal, need.quantity, conversions)
            _spend(remaining, need, conversions)
        for need in coverage.missing:
            # What is short where the pantry holds some of it, and the whole
            # amount where it holds none. A staple that is out has no number
            # to be short by, so the recipe's own amount is all there is.
            _fold(buy, _name(need), need, meal,
                  need.short if need.short else need.quantity, conversions)
        for need in coverage.uncertain:
            _fold(ask, _name(need, as_asked=True), need, meal, need.quantity, conversions)
    return Groceries(_lines(buy), _lines(ask), _lines(kept), dishes=len(wanted))


def by_aisle(lines):
    """The list grouped into the parts of a shop, in the order it is already in.

    `_lines` has already put the aisles in order and `the rest` last, so this
    only says where one section ends.
    """
    groups = []
    for line in lines:
        if not groups or groups[-1][0] != line.aisle:
            groups.append((line.aisle, []))
        groups[-1][1].append(line)
    return tuple((aisle, tuple(found)) for aisle, found in groups)


def ingredients_of(result):
    """A dish's lines, and the parts of a shop they are filed under.

    `extendedIngredients` is what /information answers with and used plus
    missed is what a search answers with, so either payload can be handed in
    and neither is treated as the authority on what the house holds - that is
    this kitchen's arithmetic to do (matching/ingredients.py).

    Cut to PER_RECIPE on the way in: `number` is a request and the ceiling
    above is a promise.
    """
    found = result.get("extendedIngredients")
    if not isinstance(found, list) or not found:
        found = (list(result.get("usedIngredients") or [])
                 + list(result.get("missedIngredients") or []))
    lines, aisles = [], {}
    for line in list(found)[:PER_RECIPE]:
        if not isinstance(line, dict):
            continue
        wording = str(line.get("original") or line.get("name") or "").strip()
        if not wording:
            continue
        lines.append(RecipeIngredient(wording, line.get("amount"), line.get("unit")))
        aisle = str(line.get("aisle") or "").strip().lower()
        if aisle:
            aisles.setdefault(normalise_name(wording), aisle)
    return tuple(lines), aisles


def still_to_cook(meal):
    """Whether a meal is still something to shop for.

    A portion of an earlier cook buys nothing: its ingredients went into the
    pan the day before. A skipped meal buys nothing either, and neither does
    one already cooked - the stock for it has moved. Replanning a week that
    went wrong is its own item; leaving a cooked dinner off the shopping is
    not replanning, it is not buying dinner twice.
    """
    return (meal["kind"] == week.COOK and meal["recipe_id"] is not None
            and not meal["skipped"] and meal["cooked_at"] is None)


def _nothing_pointed_at(row, meals):
    """Why a plan yields no list, in the one sentence a person needs.

    Four different silences, and telling them apart is the whole value of
    saying anything: a closed week, a week nothing was found for, a week
    already eaten, and a week where every slot was struck out.
    """
    if row["state"] == week.CLOSED:
        return ("this week is closed and its dishes are not pointed at any more,"
                " so there is no list to build")
    if any(meal["cooked_at"] is not None for meal in meals):
        return "every dish on this week has been cooked, so there is nothing left to buy"
    if all(meal["skipped"] or meal["kind"] is None for meal in meals):
        return "nothing was chosen for this week, so there is nothing to buy"
    return "this week holds no dish to look up, so there is nothing to buy"


def _look_up(cx, client, cooks):
    """Each distinct dish once, and what it cost to find out it could not be had.

    A dish held from an earlier render costs nothing and does not count
    against the ceiling: the whole point of the hold is that reading the list
    again inside the hour is free.

    A refusal stops the looking rather than being tried eight times: no key is
    no key, and a spent quota is spent for the rest of the day, so the calls
    after the first would buy nothing but a slower page. What came back before
    it is kept, because most of a list is worth carrying and the meals that
    are missing from it are named.

    The client is built at the first call out and not before, so a list every
    dish of which is held still renders on a board with no key set.
    """
    dishes, wanted, unknown, refusal, spent = {}, [], [], None, 0
    for meal in cooks:
        recipe_id = meal["recipe_id"]
        if recipe_id not in dishes:
            found = HELD.get(recipe_id)
            if found is None:
                if refusal is not None or spent >= MOST_LOOKUPS:
                    unknown.append(meal["id"])
                    continue
                try:
                    client = client or Spoonacular(usage=usage_into(cx))
                    found = ingredients_of(client.information(recipe_id))
                except SpoonacularError as bad:
                    refusal = _why(bad)
                    unknown.append(meal["id"])
                    continue
                spent += 1
                HELD.put(recipe_id, found)
            dishes[recipe_id] = found
        lines, aisles = dishes[recipe_id]
        wanted.append(Wanted(meal["id"], lines, aisles))
    return tuple(wanted), tuple(unknown), refusal


def _why(refusal):
    """Why the list is short, in words a person can act on."""
    if isinstance(refusal, MissingKey):
        return "there is no Spoonacular key, so the week's dishes could not be looked up"
    if isinstance(refusal, QuotaExhausted):
        return "the day's Spoonacular points are spent, so this is as far as the list got"
    return "the recipe service could not be reached: %s" % refusal


def _summary(dishes, unknown, refusal):
    """What the list is made of, and what it is missing."""
    note = "the list is made from %d %s" % (dishes, "dish" if dishes == 1 else "dishes")
    if unknown:
        note += "; %d could not be looked up" % len(unknown)
        if refusal:
            note += " - %s" % refusal
    return note


def _kitchen(cx):
    """The pantry, the answered wordings and the factors, as the matcher wants them.

    Read through planner/week.py's own readers instead of a second set of
    queries. The plan and the list have to be looking at the same pantry: two
    spellings of one question is how the week that was planned and the week
    that is shopped for start disagreeing, and nothing would say which of them
    was wrong.
    """
    return week._pantry_items(cx), week._aliases(cx), week._conversions(cx)


def _name(need, *, as_asked=False):
    """What a line is called on the list.

    The household's own name where the matcher settled it, because that is
    what is written on the shelf the thing goes back onto. Otherwise the
    wording reduced to the thing itself - "2 cups finely diced tomatoes"
    becomes "tomato" - which is as close to the household's own words as a
    line nothing matched ever gets.

    A question is always called what the recipe asked for. Asking "is this
    your imaginary parsley" under the name `imaginary parsley` would be
    putting the answer in the question, and the whole point of the third list
    is that nobody has answered it yet.
    """
    asked = normalise_name(need.wording) or need.wording.strip()
    return asked if as_asked or not need.ingredient else need.ingredient


def _fold(bucket, name, need, meal, quantity, conversions):
    """One line into the list, added to whatever is already under its name."""
    line = bucket.setdefault(name, {"meals": [], "amounts": [], "aisle": ELSEWHERE,
                                    "reason": need.reason, "candidates": need.match.candidates})
    if meal.meal not in line["meals"]:
        line["meals"].append(meal.meal)
    if line["aisle"] == ELSEWHERE:
        line["aisle"] = meal.aisles.get(normalise_name(need.wording), ELSEWHERE)
    _into(line["amounts"], quantity, need.unit, name, conversions)


def _into(amounts, quantity, unit, name, conversions):
    """Add an amount to a line, in a unit already on it where one converts.

    A line with no number stays a line: a recipe that says "a handful of
    parsley" is still parsley to buy, and inventing a quantity for it would
    put a made-up figure where a price will later hang.
    """
    if quantity is None:
        return
    unit = normalise_unit(unit) if unit is not None else None
    for held in amounts:
        if held[1] == unit:
            held[0] += quantity
            return
        moved = convert(quantity, unit, held[1], ingredient=name, conversions=conversions)
        if moved:
            held[0] += moved.quantity
            return
    amounts.append([quantity, unit])


def _spend(remaining, need, conversions):
    """Take what a meal covered out of the pantry the rest of the week reads.

    Only a measured line moves anything. A staple is in stock or it is not and
    has no quantity to spend (kitchen/pantry.py), and a line the recipe gave
    no amount for is presence rather than arithmetic, so neither is deducted.
    """
    if need.quantity is None or need.unit is None or need.ingredient is None:
        return
    left = need.quantity
    for row in remaining:
        if row["ingredient"] != need.ingredient or row["grade"] != pantry.PERISHABLE:
            continue
        if not row["quantity"]:
            continue
        moved = convert(row["quantity"], row["unit"], need.unit,
                        ingredient=need.ingredient, conversions=conversions)
        if not moved:
            continue
        taken = min(moved.quantity, left)
        back = convert(taken, need.unit, row["unit"],
                       ingredient=need.ingredient, conversions=conversions)
        row["quantity"] = max(row["quantity"] - (back.quantity if back else row["quantity"]), 0.0)
        left -= taken
        if left <= CRUMB:
            return


def _lines(bucket):
    """A bucket of folded lines as the list they are read in.

    Sorted by aisle so a shop is walked once, with `the rest` last because a
    line nothing could place should not interrupt the produce.
    """
    built = [Line(name=name,
                  amounts=tuple(Amount(quantity, unit) for quantity, unit in line["amounts"]),
                  aisle=line["aisle"], meals=tuple(line["meals"]),
                  reason=line["reason"], candidates=tuple(line["candidates"]))
             for name, line in bucket.items()]
    return tuple(sorted(built, key=lambda line: (line.aisle == ELSEWHERE,
                                                 line.aisle.lower(), line.name.lower())))
