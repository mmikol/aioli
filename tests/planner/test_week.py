"""The week: that it is built from the pantry outward, that every dish is
cooked once and eaten twice, that it says so plainly when it cannot be filled,
and that nothing the service authored reaches a table.

Every answer here comes from recipes.fixtures, which are invented and belong
to nobody. Nothing in this file has been anywhere near the service.
"""
import datetime

import psycopg
import pytest

from kitchen import moves, pantry, settings
from matching.ingredients import RecipeIngredient
from planner import week
from recipes import client
from tests.recipes import fixtures

# A Monday, so a week runs from it to the Sunday after. Written down rather
# than computed from today, because a suite whose plan shifts with the day it
# is run on is a suite that fails on a Sunday for reasons nobody can see.
MONDAY = datetime.date(2026, 9, 21)

DAYS = [MONDAY + datetime.timedelta(days=n) for n in range(7)]

# A key shaped like one and belonging to nobody.
KEY = "not-a-real-key-0000"


class Stub:
    """As much of recipes.client.Spoonacular as the planner calls.

    `error` is raised by every call, or by every call after `after` of them,
    which is how a test says "the first search answered and then the day's
    points went". `pass_error` refuses the use-it-up pass and nothing else.
    """

    def __init__(self, results=None, found=None, error=None, after=None, pass_error=None):
        self.results = fixtures.COMPLEX_SEARCH if results is None else results
        self.found = fixtures.FIND_BY_INGREDIENTS if found is None else found
        self.error = error
        self.after = after
        self.pass_error = pass_error
        self.searches = []
        self.passes = []

    def complex_search(self, **params):
        self.searches.append(params)
        if self._refusing(len(self.searches)):
            raise self.error
        return self.results

    def find_by_ingredients(self, ingredients, *, number=10):
        self.passes.append(list(ingredients))
        if self.pass_error is not None:
            raise self.pass_error
        if self._refusing(len(self.searches) + len(self.passes)):
            raise self.error
        return self.found

    def _refusing(self, call):
        return self.error is not None and (self.after is None or call > self.after)


def stock(db, today=MONDAY):
    """A pantry with one thing turning in two days and three that keep."""
    pantry.add_perishable(db, "imaginary parsley", 2, "cup", 2, acquired_on=today)
    pantry.add_perishable(db, "notional chickpeas", 2, "can", 30, acquired_on=today)
    pantry.add_staple(db, "pretend olive oil")
    pantry.add_staple(db, "make-believe rice")


def planned(db, spoon=None, **kwargs):
    """A week planned off the fixtures, for the tests that do not care how."""
    return week.plan(db, spoon or Stub(), start=MONDAY, today=MONDAY, **kwargs)


def by_slot(plan):
    """The week's meals, reachable by the slot they fill."""
    return {(meal.day, meal.slot): meal for meal in plan.meals}


def rows_by_slot(held):
    """The saved meals, reachable the same way."""
    return {(row["meal_on"], row["slot"]): row for row in held.meals}


def empty_plan(db, period="2026-W39", state="draft"):
    """A bare plan row, for the tests that are about the constraints."""
    return db.execute(
        "insert into plan (period, starts_on, ends_on, state) values (%s, %s, %s, %s)"
        " returning *", (period, MONDAY, DAYS[-1], state)).fetchone()


def test_a_period_is_the_iso_week_the_plan_starts_in():
    assert week.period_of(MONDAY) == "2026-W39"
    assert week.period_of(DAYS[-1]) == "2026-W39"


def test_a_plan_starts_on_the_monday_ahead_unless_today_is_monday():
    assert week.next_monday(today=MONDAY) == MONDAY
    assert week.next_monday(today=DAYS[1]) == MONDAY + datetime.timedelta(days=7)
    assert week.next_monday(today=DAYS[6]) == MONDAY + datetime.timedelta(days=7)


def test_a_dinner_is_cooked_and_the_next_day_eats_it_for_lunch():
    kinds, eats = week.pairing(DAYS, set())
    assert kinds[(DAYS[0], "dinner")] == week.COOK
    assert kinds[(DAYS[1], "lunch")] == week.LEFTOVERS
    assert eats[(DAYS[1], "lunch")] == (DAYS[0], "dinner")


def test_the_edges_of_the_week_are_cooked_for_one_sitting():
    kinds, eats = week.pairing(DAYS, set())
    claimed = set(eats.values())
    # The first lunch has no dinner before it inside the plan and the last
    # dinner has no lunch after it, so neither pairs. Pretending otherwise
    # would be a plan that cannot be cooked.
    assert (DAYS[0], "lunch") not in claimed
    assert (DAYS[6], "dinner") not in claimed
    assert len([key for key, how in kinds.items() if how == week.COOK]) == 8
    assert len(eats) == 6


def test_a_skipped_lunch_leaves_the_dinner_before_it_eaten_once():
    kinds, eats = week.pairing(DAYS, {(DAYS[1], "lunch")})
    assert (DAYS[1], "lunch") not in kinds
    assert (DAYS[0], "dinner") not in set(eats.values())


def test_a_lunch_with_no_dinner_behind_it_is_a_batch_of_its_own():
    kinds, eats = week.pairing(DAYS, {(DAYS[0], "dinner")})
    assert kinds[(DAYS[0], "lunch")] == week.COOK
    assert eats[(DAYS[1], "lunch")] == (DAYS[0], "lunch")


def test_the_pantry_term_leans_towards_what_turns_soonest():
    urgency = {"spinach": 2.0, "rice": 1.0}
    ageing = week.Candidate(1, ("spinach",))
    keeping = week.Candidate(2, ("rice",))
    assert week.score(ageing, urgency) > week.score(keeping, urgency)


def test_a_dish_that_must_be_bought_for_scores_below_one_that_need_not():
    urgency = {"rice": 1.0}
    held = week.Candidate(1, ("rice",))
    bought = week.Candidate(2, ("rice",), ("invented lemon", "fictional saffron"))
    assert week.score(held, urgency) > week.score(bought, urgency)


def test_what_the_week_already_buys_costs_the_next_dish_nothing():
    # The buying term is read against the week's basket and not against one
    # dish at a time: two dinners wanting the same lemon is one lemon, and a
    # count could never say so.
    urgency = {"rice": 1.0}
    candidate = week.Candidate(1, ("rice",), ("invented lemon", "fictional saffron"))
    assert week.terms(candidate, urgency)["buying"] == -2.0
    assert week.terms(candidate, urgency, basket={"invented lemon"})["buying"] == -1.0
    shares = week.Candidate(2, ("rice",), ("invented lemon",))
    alone = week.Candidate(3, ("rice",), ("fictional saffron",))
    basket = {"invented lemon"}
    assert week.score(shares, urgency, basket=basket) > week.score(alone, urgency, basket=basket)


def test_the_objective_has_two_terms_and_a_third_would_be_an_addition():
    urgency = {"rice": 1.0}
    candidate = week.Candidate(1, ("rice",), ("invented lemon", "fictional saffron"))
    assert set(week.terms(candidate, urgency)) == {"pantry", "buying"}
    # A weight for a term that does not exist yet is simply not applied, which
    # is what lets cost arrive as one more entry in each and nothing else.
    with_cost = week.score(candidate, urgency, weights=dict(week.WEIGHTS, cost=2.0))
    assert with_cost == week.score(candidate, urgency)


@pytest.mark.database
def test_a_week_is_fourteen_meals_and_the_servings_are_the_household(db):
    settings.put(db, "household_size", 2)
    stock(db)
    plan = planned(db)
    assert len(plan.meals) == 14
    assert [meal.slot for meal in plan.meals[:2]] == ["lunch", "dinner"]
    assert plan.filled
    assert {meal.servings for meal in plan.meals} == {2}


@pytest.mark.database
def test_every_dish_is_cooked_once_and_eaten_twice(db):
    stock(db)
    plan = planned(db)
    portions = [meal for meal in plan.meals if meal.kind == week.LEFTOVERS]
    assert len(portions) == 6
    for portion in portions:
        source = plan.meals[portion.eats]
        assert source.kind == week.COOK
        assert 0 <= (portion.day - source.day).days <= week.LEFTOVERS_GAP_DAYS
        # The pointer sits on the cook; a portion of it follows the pairing.
        assert portion.recipe_id is None
    assert len(plan.cooks) == 8


@pytest.mark.database
def test_the_search_goes_out_with_what_turns_soonest_in_front(db):
    stock(db)
    spoon = Stub()
    planned(db, spoon)
    include = spoon.searches[0]["include_ingredients"]
    assert include[0] == "imaginary parsley"
    assert set(include) == {"imaginary parsley", "make-believe rice",
                            "notional chickpeas", "pretend olive oil"}
    # The second pass asks about what is turning and nothing else.
    assert spoon.passes == [["imaginary parsley"]]


@pytest.mark.database
def test_the_lot_that_turns_today_is_not_buried_by_the_one_bought_to_replace_it(db):
    # turning_soonest answers one row per lot, soonest first, so assigning by
    # name let the freshest lot write last and win. Buying a replacement would
    # then erase the signal that the old one is about to be binned - in the
    # one term the MVP exists to optimise.
    pantry.add_perishable(db, "notional chicken", 1, "kg", 1, acquired_on=MONDAY)
    pantry.add_perishable(db, "notional chicken", 1, "kg", 6, acquired_on=MONDAY)
    urgency = week._urgency(db, MONDAY + datetime.timedelta(days=1))
    assert urgency["notional chicken"] == week.URGENT_WEIGHT


@pytest.mark.database
def test_two_lots_of_one_thing_are_one_word_to_search_with(db):
    pantry.add_perishable(db, "notional chicken", 1, "kg", 2, acquired_on=MONDAY)
    pantry.add_perishable(db, "notional chicken", 1, "kg", 3, acquired_on=MONDAY)
    spoon = Stub()
    planned(db, spoon)
    assert spoon.passes == [["notional chicken"]]
    assert spoon.searches[0]["include_ingredients"].count("notional chicken") == 1


@pytest.mark.database
def test_one_search_per_ready_time_cap_and_no_more(db):
    stock(db)
    spoon = Stub()
    planned(db, spoon)
    assert sorted(search["max_ready_time"] for search in spoon.searches) == [45, 90]
    # A dish that cannot yield two sittings cannot be cooked once and eaten
    # twice, so the floor is the household doubled.
    assert {search["min_servings"] for search in spoon.searches} == {2}
    assert len(spoon.searches) + len(spoon.passes) == 3


@pytest.mark.database
def test_what_the_household_will_not_eat_rides_on_the_search(db):
    stock(db)
    settings.add_dietary_rule(db, "diet", "vegetarian")
    settings.add_dietary_rule(db, "intolerance", "gluten")
    settings.add_dietary_rule(db, "dislike", "olives")
    spoon = Stub()
    planned(db, spoon)
    assert spoon.searches[0]["diet"] == "vegetarian"
    assert spoon.searches[0]["intolerances"] == ["gluten"]
    assert spoon.searches[0]["exclude_ingredients"] == ["olives"]


@pytest.mark.database
def test_a_dish_wanting_a_pan_this_kitchen_lacks_is_dropped(db):
    stock(db)
    settings.add_equipment(db, "frying pan", present=False)
    wants_a_pan = dict(fixtures.COMPLEX_SEARCH["results"][0],
                       analyzedInstructions=fixtures.INFORMATION["analyzedInstructions"])
    spoon = Stub(results={"results": [wants_a_pan, fixtures.COMPLEX_SEARCH["results"][1]]},
                 found=[])
    chosen = {meal.recipe_id for meal in planned(db, spoon).cooks}
    assert 9001 not in chosen
    assert chosen == {9002}


@pytest.mark.database
def test_the_dish_that_uses_what_turns_soonest_wins_the_first_cook(db):
    stock(db)
    first = planned(db).meals[0]
    assert first.kind == week.COOK
    assert first.recipe_id == 9002
    assert "imaginary parsley" in first.uses
    assert first.to_buy == 0


@pytest.mark.database
def test_the_pantry_is_counted_once_however_many_dishes_want_it(db):
    stock(db)
    plan = planned(db)
    # The second cook cannot be paid again for the parsley the first one ate.
    assert plan.meals[0].recipe_id == 9002
    assert plan.meals[1].recipe_id == 9001


@pytest.mark.database
def test_a_dish_with_no_known_ready_time_only_lands_where_there_is_time(db):
    stock(db)
    plan = planned(db)
    # findByIngredients takes no time filter, so 9003's ready time is unknown
    # and it goes on a day with the household's most generous cap.
    assert 9003 in {meal.recipe_id for meal in plan.cooks}
    for meal in plan.cooks:
        if meal.recipe_id == 9003:
            assert meal.day.weekday() >= 5


@pytest.mark.database
def test_a_dish_whose_yield_is_unknown_is_cooked_for_one_sitting(db):
    # findByIngredients takes no min_servings and returns no servings, so what
    # 9003 yields is unknown. A lunch written as its second helping is a lunch
    # nobody can eat if the dish serves one.
    stock(db)
    plan = planned(db)
    claimed = {meal.eats for meal in plan.meals if meal.kind == week.LEFTOVERS}
    turning = [index for index, meal in enumerate(plan.meals) if meal.recipe_id == 9003]
    assert turning
    assert not set(turning) & claimed
    assert plan.meals[turning[0]].note == week.ONE_SITTING


@pytest.mark.database
def test_a_dish_from_the_use_it_up_pass_that_says_what_it_yields_may_be_paired(db):
    # The yield is what the rule is about, and the pass it came back from is
    # only the usual reason it is unknown.
    stock(db)
    feeds_eight = [dict(fixtures.FIND_BY_INGREDIENTS[0], servings=8)]
    plan = planned(db, Stub(results={"results": []}, found=feeds_eight))
    claimed = {meal.eats for meal in plan.meals if meal.kind == week.LEFTOVERS}
    assert claimed
    assert all(plan.meals[index].recipe_id == 9003 for index in claimed)


@pytest.mark.database
def test_a_line_two_dishes_want_is_charged_to_the_week_once(db):
    stock(db)
    both_want_the_lemon = {"results": [
        fixtures.COMPLEX_SEARCH["results"][0],
        dict(fixtures.COMPLEX_SEARCH["results"][0], id=9007),
    ]}
    plan = planned(db, Stub(results=both_want_the_lemon, found=[]))
    # Eight cooks, all of them wanting the one lemon the house does not have,
    # and the week is charged for one lemon.
    assert len(plan.cooks) == 8
    assert plan.terms["buying"] == -1.0


@pytest.mark.database
def test_the_meals_marked_skipped_are_left_empty(db):
    stock(db)
    struck = [(DAYS[0], "dinner"), (DAYS[1], "lunch")]
    plan = planned(db, skipped=struck)
    meals = by_slot(plan)
    for key in struck:
        meal = meals[key]
        assert meal.skipped
        assert meal.kind is None
        assert meal.recipe_id is None
        assert meal.servings == 0
    assert plan.filled


@pytest.mark.database
def test_a_week_with_nothing_open_asks_the_service_nothing(db):
    stock(db)
    spoon = Stub()
    plan = planned(db, spoon, skipped=[(day, slot) for day in DAYS
                                       for slot in ("lunch", "dinner")])
    assert spoon.searches == [] and spoon.passes == []
    assert all(meal.skipped for meal in plan.meals)
    assert "nothing to plan" in plan.note


@pytest.mark.database
def test_with_no_key_the_week_says_so_rather_than_half_planning(db, monkeypatch):
    monkeypatch.delenv("SPOONACULAR_KEY", raising=False)
    stock(db)
    plan = week.plan(db, start=MONDAY, today=MONDAY)
    assert len(plan.meals) == 14
    assert plan.empty
    assert not plan.filled
    assert all(meal.kind is None and meal.recipe_id is None for meal in plan.meals)
    assert "no Spoonacular key" in plan.note


@pytest.mark.database
def test_a_spent_quota_is_a_week_that_says_so(db):
    stock(db)

    def opener(request, timeout=None):
        raise fixtures.quota_exhausted_error()

    plan = week.plan(db, client.Spoonacular(key=KEY, opener=opener),
                     start=MONDAY, today=MONDAY)
    assert plan.empty
    assert "points are spent" in plan.note


@pytest.mark.database
def test_a_refusal_on_the_use_it_up_pass_does_not_throw_the_week_away(db):
    # The use-it-up pass is the optional second one. A 402 on it used to
    # discard every dish the searches before it had returned, and the points
    # those searches cost with them.
    stock(db)
    spoon = Stub(pass_error=client.QuotaExhausted("spent", status=402))
    plan = planned(db, spoon)
    assert plan.filled
    assert len(plan.cooks) == 8
    assert "the week is planned" in plan.note
    assert "one of the searches was refused" in plan.note
    assert "points are spent" in plan.note


@pytest.mark.database
def test_a_refusal_after_the_first_search_keeps_what_the_first_one_returned(db):
    stock(db)
    spoon = Stub(error=client.QuotaExhausted("spent", status=402), after=1)
    plan = planned(db, spoon)
    # The tightest cap answered, and its dishes fit every day of the week.
    assert plan.filled
    assert "one of the searches was refused" in plan.note


@pytest.mark.database
def test_a_week_whose_every_search_was_refused_still_says_why(db):
    stock(db)
    plan = planned(db, Stub(error=client.QuotaExhausted("spent", status=402)))
    assert plan.empty
    assert "points are spent" in plan.note


@pytest.mark.database
def test_a_search_that_finds_nothing_cookable_is_not_half_a_week(db):
    stock(db)
    plan = planned(db, Stub(results={"results": []}, found=[]))
    assert plan.empty
    assert all(meal.kind is None for meal in plan.meals)
    assert "nothing came back" in plan.note


@pytest.mark.database
def test_a_week_saved_is_a_week_read_back(db):
    stock(db)
    plan = planned(db)
    row = week.save(db, plan)
    assert row["period"] == "2026-W39"
    assert row["state"] == "draft"
    assert (row["starts_on"], row["ends_on"]) == (MONDAY, DAYS[-1])
    held = week.read(db, row["id"])
    assert len(held.meals) == 14
    saved = {meal["id"]: meal for meal in held.meals}
    for meal in held.meals:
        if meal["kind"] == "leftovers":
            assert saved[meal["pairs_with"]]["kind"] == "cook"
            assert meal["recipe_id"] is None
        if meal["recipe_id"] is not None:
            assert meal["kind"] == "cook"


@pytest.mark.database
def test_a_week_nothing_could_be_found_for_is_saved_as_unfilled(db, monkeypatch):
    monkeypatch.delenv("SPOONACULAR_KEY", raising=False)
    stock(db)
    row = week.save(db, week.plan(db, start=MONDAY, today=MONDAY))
    assert row["state"] == "unfilled"
    assert "no Spoonacular key" in row["note"]
    assert len(week.read(db, row["id"]).meals) == 14


def written(db, tables):
    """Every value in every one of these tables, lowercased, as one haystack."""
    found = []
    for table in tables:
        for row in db.execute("select * from " + table).fetchall():
            found.extend(str(value).lower() for value in row.values() if value is not None)
    return " ".join(found)


def every_table(db):
    """The tables the schema holds, asked for rather than listed.

    Asked, so a table a later migration adds is inside the sweep below the day
    it lands. A hard rule guarded by a hand-written list is a rule that holds
    until somebody writes a migration and forgets (docs/db.md).
    """
    return [row["table_name"] for row in db.execute(
        "select table_name from information_schema.tables"
        " where table_schema = current_schema() and table_name <> 'schema_migrations'"
    ).fetchall()]


def service_prose():
    """What the invented service authored: the titles, and the method's steps.

    A household types an ingredient into its pantry and never types a recipe's
    name or a line of its method anywhere, so one of these found in any table
    is the line in docs/db.md being crossed. The ingredient wordings are not
    here for the opposite reason: this suite's own pantry is spelled out of
    the same invented vocabulary, and a name the household wrote down is the
    household's whatever it resembles.
    """
    dishes = (list(fixtures.COMPLEX_SEARCH["results"]) + list(fixtures.FIND_BY_INGREDIENTS)
              + [fixtures.INFORMATION])
    found = {str(dish["title"]).lower() for dish in dishes if dish.get("title")}
    for block in fixtures.INFORMATION.get("analyzedInstructions") or ():
        found.update(str(step["step"]).lower() for step in block.get("steps") or ())
    return found


@pytest.mark.database
def test_nothing_the_service_wrote_reaches_a_table(db):
    stock(db)
    plan = planned(db)
    row = week.save(db, plan)
    tables = every_table(db)
    assert "plan_meal" in tables

    # The service's own prose - a dish's name, a step of its method - is a
    # thing no household types anywhere, so it is looked for in every table
    # the schema holds rather than in the two the planner writes.
    everywhere = written(db, tables)
    authored = service_prose()
    assert authored
    for phrase in authored:
        assert phrase not in everywhere, "%r reached a table" % phrase

    # The invented words on their own are swept over the two tables the
    # planner writes rather than over all of them: this test typed some of
    # them into the pantry itself, and a name the household wrote down is the
    # household's whatever it resembles.
    planned_rows = written(db, ("plan", "plan_meal"))
    for marker in fixtures.SYNTHETIC_MARKERS:
        assert marker not in planned_rows, "%s reached a table" % marker

    # The single permitted pointer, and it is an integer and nothing else.
    pointers = {meal["recipe_id"] for meal in week.read(db, row["id"]).meals} - {None}
    assert pointers <= {9001, 9002, 9003}
    assert all(isinstance(pointer, int) for pointer in pointers)


@pytest.mark.database
def test_closing_a_period_purges_the_pointers(db):
    stock(db)
    plan = planned(db)
    row = week.save(db, plan)
    assert week.close(db, row["id"]) == len(plan.cooks)
    held = week.read(db, row["id"])
    assert held.row["state"] == "closed"
    assert held.row["closed_at"] is not None
    assert all(meal["recipe_id"] is None for meal in held.meals)
    # A second close has nothing left to purge, which is the point.
    assert week.close(db, row["id"]) == 0


@pytest.mark.database
def test_planning_a_week_closes_the_weeks_whose_period_has_passed(db):
    # The purge has to have a caller that exists today. The scheduler that
    # would run it on a clock is an item below the MVP, and until it lands a
    # promise nothing calls is a promise nobody keeps (docs/db.md).
    stock(db)
    over = week.save(db, planned(db))
    week.save(db, week.plan(db, Stub(), start=DAYS[-1] + datetime.timedelta(days=1),
                            today=DAYS[-1] + datetime.timedelta(days=1)))
    held = week.read(db, over["id"])
    assert held.row["state"] == "closed"
    assert held.row["closed_at"] is not None
    assert all(meal["recipe_id"] is None for meal in held.meals)


@pytest.mark.database
def test_the_week_being_eaten_is_left_alone_by_the_purge(db):
    stock(db)
    row = week.save(db, planned(db))
    assert week.close_passed(db, today=MONDAY) == 0
    assert week.read(db, row["id"]).row["state"] == "draft"

    after_it_ended = DAYS[-1] + datetime.timedelta(days=1)
    assert week.close_passed(db, today=after_it_ended) == 8
    assert week.read(db, row["id"]).row["state"] == "closed"
    # A second run has nothing left to purge, which is the point.
    assert week.close_passed(db, today=after_it_ended) == 0


@pytest.mark.database
def test_skipping_a_cook_empties_it_and_whatever_would_have_eaten_it(db):
    stock(db)
    row = week.save(db, planned(db))
    saved = rows_by_slot(week.read(db, row["id"]))
    cook = saved[(DAYS[0], "dinner")]
    portion = saved[(DAYS[1], "lunch")]
    assert portion["pairs_with"] == cook["id"]

    week.skip(db, cook["id"])
    after = {meal["id"]: meal for meal in week.read(db, row["id"]).meals}
    assert after[cook["id"]]["skipped"]
    assert after[cook["id"]]["recipe_id"] is None
    assert after[cook["id"]]["servings"] == 0
    assert after[portion["id"]]["kind"] is None
    assert after[portion["id"]]["pairs_with"] is None
    assert not after[portion["id"]]["skipped"]


@pytest.mark.database
def test_confirming_a_cook_moves_the_stock_once(db):
    stock(db)
    row = week.save(db, planned(db))
    cook = rows_by_slot(week.read(db, row["id"]))[(DAYS[0], "dinner")]
    # The recipe's own wording, as the stove hands it over: the matching
    # against the household's name is the planner's to do.
    lines = [RecipeIngredient("1 can notional chickpeas", 1, "can")]

    week.confirm_cooked(db, cook["id"], lines=lines)
    # The same tap arriving twice from a phone on a bad connection.
    week.confirm_cooked(db, cook["id"], lines=lines)

    assert pantry.find(db, "notional chickpeas")["quantity"] == 1
    assert len(moves.caused_by(db, "plan_meal:%d" % cook["id"])) == 1
    after = {meal["id"]: meal for meal in week.read(db, row["id"]).meals}
    assert after[cook["id"]]["cooked_at"] is not None


@pytest.mark.database
def test_confirming_a_portion_of_an_earlier_cook_moves_nothing(db):
    stock(db)
    row = week.save(db, planned(db))
    portion = rows_by_slot(week.read(db, row["id"]))[(DAYS[1], "lunch")]
    assert portion["kind"] == "leftovers"

    week.confirm_cooked(db, portion["id"])

    # The stock went when the dish was cooked; eating the second portion is
    # not a second subtraction.
    assert moves.recent(db) == []
    after = {meal["id"]: meal for meal in week.read(db, row["id"]).meals}
    assert after[portion["id"]]["cooked_at"] is not None


@pytest.mark.database
def test_a_skipped_meal_may_not_hold_a_dish(db):
    plan_id = empty_plan(db)["id"]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "insert into plan_meal (plan_id, meal_on, slot, kind, recipe_id, skipped)"
            " values (%s, %s, 'dinner', 'cook', 9001, true)", (plan_id, MONDAY))


@pytest.mark.database
def test_only_a_cook_may_point_at_a_recipe(db):
    plan_id = empty_plan(db)["id"]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("insert into plan_meal (plan_id, meal_on, slot, recipe_id)"
                   " values (%s, %s, 'lunch', 9001)", (plan_id, MONDAY))


@pytest.mark.database
def test_a_portion_comes_from_a_cook_or_from_nowhere(db):
    plan_id = empty_plan(db)["id"]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("insert into plan_meal (plan_id, meal_on, slot, kind, servings)"
                   " values (%s, %s, 'lunch', 'leftovers', 1)", (plan_id, MONDAY))


@pytest.mark.database
def test_a_period_has_one_live_plan(db):
    empty_plan(db, state="live")
    empty_plan(db, state="draft")
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        empty_plan(db, state="live")
