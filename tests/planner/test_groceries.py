"""The list: that it subtracts the pantry once, keeps the three answers apart,
says what the week shares and what it buys for one meal only, and stores
nothing at all.

Every dish here is invented in this file, to the shape of the API and
belonging to nobody, because a fixture is a place data gets held for years
and a recipe may not be (docs/db.md). Nothing in this file has been near the
service.

The board's two views are tested at the foot rather than in tests/board,
because the page is the list's only reader: what it renders is these same
lines, and a test of it that lived away from them would be a test of the
HTML rather than of the answer.
"""
import datetime

import pytest

from board import plan_pages
from kitchen import pantry
from matching.ingredients import PantryItem, RecipeIngredient
from planner import groceries, week
from recipes import client, fixtures
from recipes.hold import HOLD_SECONDS, Hold

# A Monday, written down rather than computed, so the suite does not plan a
# different week depending on the day it is run.
MONDAY = datetime.date(2026, 9, 21)
TUESDAY = MONDAY + datetime.timedelta(days=1)
SUNDAY = MONDAY + datetime.timedelta(days=6)

# A key shaped like one and belonging to nobody.
KEY = "not-a-real-key-0000"


def line(name, amount, unit, aisle=None, wording=None):
    """One ingredient line, in the shape both the search and /information use."""
    made = {"id": abs(hash(name)) % 10000, "name": name, "amount": amount, "unit": unit,
            "original": wording or ("%s %s %s" % (amount, unit, name)).strip()}
    if aisle:
        made["aisle"] = aisle
    return made


def dish(recipe_id, *lines):
    """An /information answer, invented, carrying only what the list reads."""
    return {"id": recipe_id, "readyInMinutes": 35, "servings": 4,
            "extendedIngredients": list(lines)}


DISHES = {
    9001: dish(9001,
               line("notional chickpeas", 400, "g", "canned and jarred"),
               line("invented lemon", 1, "", "produce"),
               line("pretend olive oil", 2, "tbsp", "oil, vinegar, salad dressing")),
    9002: dish(9002,
               line("notional chickpeas", 400, "g", "canned and jarred"),
               line("fictional saffron", 1, "pinch", "spices and seasonings")),
}


class Dishes:
    """As much of recipes.client.Spoonacular as the list calls.

    `asked` is the whole point of it: one lookup per distinct dish is the
    ceiling planner/groceries.py states, and a stub that counts is the only
    thing that can hold it to it.
    """

    def __init__(self, dishes=None, error=None, after=None):
        self.dishes = DISHES if dishes is None else dishes
        self.error = error
        self.after = after
        self.asked = []

    def information(self, recipe_id, *, nutrition=False):
        self.asked.append(recipe_id)
        if self.error is not None and (self.after is None or len(self.asked) > self.after):
            raise self.error
        return self.dishes[recipe_id]


class Clock:
    """A clock the test moves by hand, because an hour is not worth waiting."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def forward(self, seconds):
        self.now += seconds


def wants(meal, *lines, aisles=None):
    """One meal's lines, as they reach the arithmetic."""
    return groceries.Wanted(meal, tuple(lines), aisles or {})


def asks(wording, quantity=None, unit=None):
    return RecipeIngredient(wording, quantity, unit)


def held(*items):
    return list(items)


def perishable(name, quantity, unit):
    return PantryItem(name, quantity, unit, pantry.PERISHABLE, None)


def staple(name, level="in_stock"):
    return PantryItem(name, None, None, pantry.STAPLE, level)


def named(lines):
    """A list by name, which is how every assertion below reads it."""
    return {found.name: found for found in lines}


# --- the three answers ----------------------------------------------------

def test_the_three_answers_stay_apart():
    found = groceries.gather(
        [wants(1,
               asks("400 g notional chickpeas", 400, "g"),
               asks("200 g invented lemon", 200, "g"),
               asks("1/4 cup chopped imaginary parsnip", 0.25, "cup"))],
        held(perishable("notional chickpeas", 400, "g"),
             perishable("imaginary parsley", 2, "cup")))
    assert [found.name for found in found.buy] == ["invented lemon"]
    # A wording that resembles something on the shelf without anybody having
    # said so is a question and not a silent yes.
    assert [found.name for found in found.ask] == ["imaginary parsnip"]
    assert "nobody has said" in found.ask[0].reason
    assert [found.name for found in found.held] == ["notional chickpeas"]


def test_an_uncertain_line_asks_under_the_name_the_recipe_used():
    found = groceries.gather(
        [wants(1, asks("1/4 cup chopped imaginary parsnip", 0.25, "cup"))],
        held(perishable("imaginary parsley", 2, "cup")))
    # The question is whether the parsnip is the parsley, and asking it under
    # the parsley's name would be putting the answer in the question.
    assert found.ask[0].name == "imaginary parsnip"
    assert found.ask[0].candidates[0][0] == "imaginary parsley"
    # It is neither bought nor assumed away: it is asked about.
    assert not found.buy and not found.held
    assert not found.empty


def test_a_staple_in_stock_is_not_bought_however_many_meals_want_it():
    found = groceries.gather(
        [wants(1, asks("2 tbsp pretend olive oil", 2, "tbsp")),
         wants(2, asks("1 tbsp pretend olive oil", 1, "tbsp"))],
        held(staple("pretend olive oil")))
    assert not found.buy
    assert found.held[0].meals == (1, 2)
    assert found.empty


def test_a_staple_that_is_out_is_bought():
    found = groceries.gather(
        [wants(1, asks("2 tbsp pretend olive oil", 2, "tbsp"))],
        held(staple("pretend olive oil", "out")))
    assert [found.name for found in found.buy] == ["pretend olive oil"]
    assert found.buy[0].said == "2 tbsp"


# --- the pantry is spent once ---------------------------------------------

def test_the_same_stock_is_not_promised_to_two_meals():
    found = groceries.gather(
        [wants(1, asks("400 g notional chickpeas", 400, "g")),
         wants(2, asks("400 g notional chickpeas", 400, "g"))],
        held(perishable("notional chickpeas", 400, "g")))
    # Monday eats what is in the house; Thursday is shopped for. A list that
    # said otherwise would send the household home short of one dinner.
    assert named(found.held)["notional chickpeas"].meals == (1,)
    assert named(found.buy)["notional chickpeas"].meals == (2,)
    assert named(found.buy)["notional chickpeas"].said == "400 g"


def test_what_is_left_after_one_meal_is_what_the_next_is_short_of():
    found = groceries.gather(
        [wants(1, asks("300 g notional chickpeas", 300, "g")),
         wants(2, asks("400 g notional chickpeas", 400, "g"))],
        held(perishable("notional chickpeas", 500, "g")))
    assert named(found.buy)["notional chickpeas"].said == "200 g"


def test_the_pantry_is_spent_in_the_unit_it_is_held_in():
    found = groceries.gather(
        [wants(1, asks("1 cup notional stock", 1, "cup")),
         wants(2, asks("1 cup notional stock", 1, "cup"))],
        held(perishable("notional stock", 300, "ml")))
    # 300 ml answers the first cup and leaves 63 ml, so the second is short by
    # the difference and not by a whole cup.
    short = named(found.buy)["notional stock"].amounts[0]
    assert short.unit == "cup"
    assert 0.7 < short.quantity < 0.8


def test_a_line_with_no_amount_is_still_a_line():
    found = groceries.gather(
        [wants(1, asks("a handful of imaginary parsley"))],
        held(perishable("notional chickpeas", 400, "g")))
    # The amount and its unit open the phrase and are stripped with it, which
    # leaves the thing itself and nothing to shop by.
    assert [found.name for found in found.buy] == ["imaginary parsley"]
    # No number is invented for it: what the recipe said is all there is.
    assert found.buy[0].said == ""


# --- one list, and what it says about waste -------------------------------

def test_two_meals_wanting_one_thing_make_one_line():
    found = groceries.gather(
        [wants(1, asks("1 cup invented lemon juice", 1, "cup")),
         wants(2, asks("2 tbsp invented lemon juice", 2, "tbsp"))],
        held())
    assert len(found.buy) == 1
    only = found.buy[0]
    assert only.meals == (1, 2)
    assert only.shared
    # A cup and two tablespoons are the same kind of number, so they add.
    assert only.said == "1.125 cup"


def test_amounts_that_do_not_convert_stay_two_honest_amounts():
    found = groceries.gather(
        [wants(1, asks("1 can notional chickpeas", 1, "can")),
         wants(2, asks("200 g notional chickpeas", 200, "g"))],
        held())
    said = found.buy[0].said
    # Nothing says what a can weighs, and inventing it would put a made-up
    # figure where a price will later hang.
    assert said == "1 can and 200 g"
    assert len(found.buy[0].amounts) == 2


def test_the_week_reports_what_it_shares_and_what_it_buys_for_one_meal():
    found = groceries.gather(
        [wants(1,
               asks("1 cup invented lemon juice", 1, "cup"),
               asks("1 pinch fictional saffron", 1, "pinch")),
         wants(2, asks("1 cup invented lemon juice", 1, "cup"))],
        held())
    assert [found.name for found in found.shared] == ["invented lemon juice"]
    assert [found.name for found in found.alone] == ["fictional saffron"]
    assert found.overlap == 0.5


def test_a_list_with_nothing_on_it_divides_by_nothing():
    found = groceries.gather([wants(1, asks("2 tbsp pretend olive oil", 2, "tbsp"))],
                             held(staple("pretend olive oil")))
    assert found.overlap == 0.0


# --- the parts of a shop --------------------------------------------------

def test_a_line_carries_the_aisle_the_shop_files_it_under():
    found = groceries.gather(
        [wants(1,
               asks("1 invented lemon", 1, ""),
               asks("1 pinch fictional saffron", 1, "pinch"),
               aisles={"invented lemon": "produce"})],
        held())
    assert named(found.buy)["invented lemon"].aisle == "produce"
    assert named(found.buy)["fictional saffron"].aisle == groceries.ELSEWHERE


def test_the_list_is_grouped_by_aisle_with_the_rest_last():
    found = groceries.gather(
        [wants(1,
               asks("1 invented lemon", 1, ""),
               asks("400 g notional chickpeas", 400, "g"),
               asks("1 pinch fictional saffron", 1, "pinch"),
               aisles={"invented lemon": "produce",
                       "notional chickpea": "canned and jarred"})],
        held())
    grouped = groceries.by_aisle(found.buy)
    assert [aisle for aisle, _lines in grouped] == [
        "canned and jarred", "produce", groceries.ELSEWHERE]


def test_an_amount_is_said_the_way_a_person_writes_it():
    assert groceries.Amount(2.0, "cup").said == "2 cup"
    # A count is a count: two lemons, not two pieces of lemon.
    assert groceries.Amount(2.0, "piece").said == "2"
    assert groceries.Amount(None, "g").said == ""


# --- what is read off a payload -------------------------------------------

def test_either_payload_shape_is_read():
    lines, aisles = groceries.ingredients_of(DISHES[9001])
    assert [each.wording for each in lines][0] == "400 g notional chickpeas"
    assert aisles["notional chickpea"] == "canned and jarred"
    # A search result carries its lines under two other names.
    lines, _aisles = groceries.ingredients_of(fixtures.COMPLEX_SEARCH["results"][0])
    assert len(lines) == 3


def test_a_payload_is_cut_on_the_way_in():
    huge = dish(9009, *[line("notional thing %d" % n, 1, "g") for n in range(200)])
    lines, _aisles = groceries.ingredients_of(huge)
    assert len(lines) == groceries.PER_RECIPE


# --- against a saved plan -------------------------------------------------

def stock(db):
    """A pantry holding one of the week's things and not the others."""
    pantry.add_perishable(db, "notional chickpeas", 400, "g", 30, acquired_on=MONDAY)
    pantry.add_staple(db, "pretend olive oil")


def a_week(db, meals=None, state=None):
    """A saved plan, written through the planner's own writer."""
    meals = meals or (
        week.Meal(MONDAY, "lunch", 2, week.COOK, 9001),
        week.Meal(MONDAY, "dinner", 2, week.COOK, 9002),
        week.Meal(TUESDAY, "lunch", 2, week.LEFTOVERS, eats=1),
        week.Meal(TUESDAY, "dinner", 2, week.COOK, 9001),
    )
    return week.save(db, week.Week("2026-W39", MONDAY, SUNDAY, meals, "a week"), state=state)


def meals_of(db, plan_id):
    return {(row["meal_on"], row["slot"]): row for row in week.read(db, plan_id)["meals"]}


@pytest.mark.database
def test_a_dish_is_looked_up_once_however_many_days_cook_it(db):
    stock(db)
    row = a_week(db)
    spoon = Dishes()
    found = groceries.for_plan(db, row["id"], spoon)
    assert spoon.asked == [9001, 9002]
    assert found.period == "2026-W39"
    # Three meals were shopped for and two dishes were looked up for them.
    assert found.dishes == 3
    assert "made from 3 dishes" in found.note


@pytest.mark.database
def test_the_list_is_the_week_against_the_pantry(db):
    stock(db)
    row = a_week(db)
    found = groceries.for_plan(db, row["id"], Dishes())
    bought = named(found.buy)
    # The house holds one 400 g lot and three dishes want 400 g each, so two
    # of them are shopped for and the first is not.
    assert bought["notional chickpeas"].said == "800 g"
    assert len(bought["notional chickpeas"].meals) == 2
    assert named(found.held)["notional chickpeas"].said == "400 g"
    # A staple in stock is carried by nobody.
    assert "pretend olive oil" in named(found.held)
    assert "pretend olive oil" not in bought


@pytest.mark.database
def test_a_portion_of_an_earlier_cook_is_shopped_for_nowhere(db):
    stock(db)
    row = a_week(db)
    portion = meals_of(db, row["id"])[(TUESDAY, "lunch")]
    found = groceries.for_plan(db, row["id"], Dishes())
    for line in found.buy + found.ask + found.held:
        assert portion["id"] not in line.meals


@pytest.mark.database
def test_a_meal_already_cooked_is_not_shopped_for_twice(db):
    stock(db)
    row = a_week(db)
    week.confirm_cooked(db, meals_of(db, row["id"])[(MONDAY, "dinner")]["id"])
    spoon = Dishes()
    groceries.for_plan(db, row["id"], spoon)
    # 9002 was that meal's dish and nothing else this week cooks it.
    assert spoon.asked == [9001]


@pytest.mark.database
def test_a_skipped_meal_is_shopped_for_nowhere(db):
    stock(db)
    row = a_week(db)
    week.skip(db, meals_of(db, row["id"])[(MONDAY, "lunch")]["id"])
    spoon = Dishes()
    groceries.for_plan(db, row["id"], spoon)
    # Tuesday's dinner still cooks 9001, so it is looked up for that and once.
    assert spoon.asked == [9002, 9001]


@pytest.mark.database
def test_a_closed_week_has_no_list_and_asks_for_none(db):
    stock(db)
    row = a_week(db)
    week.close(db, row["id"])
    spoon = Dishes()
    found = groceries.for_plan(db, row["id"], spoon)
    assert spoon.asked == []
    assert found.empty
    assert "closed" in found.note


@pytest.mark.database
def test_a_week_nothing_was_chosen_for_says_so(db):
    stock(db)
    row = a_week(db, meals=(week.Meal(MONDAY, "lunch"), week.Meal(MONDAY, "dinner")),
                 state=week.UNFILLED)
    found = groceries.for_plan(db, row["id"], Dishes())
    assert found.empty
    assert "nothing was chosen" in found.note


@pytest.mark.database
def test_a_list_that_could_not_be_built_does_not_read_as_nothing_to_buy(db, monkeypatch):
    stock(db)
    a_week(db)
    monkeypatch.delenv("SPOONACULAR_KEY", raising=False)
    page = plan_pages.groceries_page(db, {}, today=MONDAY)
    assert "no Spoonacular key" in page
    # The two silences are opposite and the page says which this one is.
    assert "the week is cooked from what is already in the house" not in page


def test_a_list_the_quota_cut_short_does_not_say_the_house_has_everything():
    # The dish that was fetched happens to be covered by the pantry, which is
    # the expected case for a pantry-led planner, so the list is empty and
    # seven dinners are missing from it. The reassurance is the last line a
    # person reads before an aisle, and it is read off `unknown`.
    cut_short = groceries.Groceries(
        dishes=1, unknown=(2, 3, 4, 5, 6, 7, 8),
        held=(groceries.Line("notional chickpeas"),),
        note="the list is made from 1 dish; 7 could not be looked up")
    said = plan_pages._summary(cut_short)
    assert "the week is cooked from what is already in the house" not in said
    assert "short of 7 meals" in said


def test_a_list_that_is_whole_and_empty_still_says_the_house_has_everything():
    found = groceries.Groceries(dishes=3, held=(groceries.Line("notional chickpeas"),))
    assert "the week is cooked from what is already in the house" in plan_pages._summary(found)


@pytest.mark.database
def test_a_week_the_house_can_already_cook_says_so(db, monkeypatch):
    pantry.add_staple(db, "notional chickpeas")
    pantry.add_staple(db, "pretend olive oil")
    pantry.add_staple(db, "invented lemon")
    pantry.add_staple(db, "fictional saffron")
    a_week(db)
    monkeypatch.setattr(groceries, "Spoonacular", lambda **kwargs: Dishes())
    page = plan_pages.groceries_page(db, {}, today=MONDAY)
    assert "the week is cooked from what is already in the house" in page


@pytest.mark.database
def test_a_list_read_again_inside_the_hour_spends_nothing(db, monkeypatch):
    # A phone left on the list in an aisle, a pull-to-refresh, a tap back from
    # the week: each of those renders the page again, and a lookup per dish
    # per render would take a day's points in six loads (pm/backlog.md).
    stock(db)
    a_week(db)
    spoon = Dishes()
    monkeypatch.setattr(groceries, "Spoonacular", lambda **kwargs: spoon)
    first = plan_pages.groceries_page(db, {}, today=MONDAY)
    again = plan_pages.groceries_page(db, {}, today=MONDAY)
    assert spoon.asked == [9001, 9002]
    assert first == again


@pytest.mark.database
def test_the_list_lets_go_of_a_dish_at_the_hour(db, monkeypatch):
    # The hour is the terms' and it is not negotiable: past it the dish is
    # fetched again rather than answered from memory (docs/db.md).
    stock(db)
    row = a_week(db)
    clock = Clock()
    monkeypatch.setattr(groceries, "HELD", Hold(clock=clock, sweep_every=3600))
    spoon = Dishes()
    groceries.for_plan(db, row["id"], spoon)
    clock.forward(HOLD_SECONDS)
    groceries.for_plan(db, row["id"], spoon)
    assert spoon.asked == [9001, 9002, 9001, 9002]


@pytest.mark.database
def test_a_list_every_dish_of_which_is_held_needs_no_key(db, monkeypatch):
    # The client is built at the first call out and not before, so a board
    # whose key has gone still renders what it already has.
    stock(db)
    row = a_week(db)
    groceries.for_plan(db, row["id"], Dishes())
    monkeypatch.delenv("SPOONACULAR_KEY", raising=False)
    found = groceries.for_plan(db, row["id"])
    assert found.buy
    assert not found.unknown


@pytest.mark.database
def test_a_plan_that_is_not_there_is_not_a_list(db):
    assert groceries.for_plan(db, 404, Dishes()) is None


@pytest.mark.database
def test_with_no_key_the_list_says_so_rather_than_half_a_list(db, monkeypatch):
    monkeypatch.delenv("SPOONACULAR_KEY", raising=False)
    stock(db)
    row = a_week(db)
    found = groceries.for_plan(db, row["id"])
    assert found.empty
    assert "no Spoonacular key" in found.note
    # Every meal it could not look up is named rather than quietly dropped,
    # and no dish was read, which is what tells this from a week the house
    # can already cook.
    assert len(found.unknown) == 3
    assert found.dishes == 0


@pytest.mark.database
def test_a_spent_quota_keeps_what_it_got_and_names_the_rest(db):
    stock(db)
    row = a_week(db)
    spoon = Dishes(error=client.QuotaExhausted("spent", status=402), after=1)
    found = groceries.for_plan(db, row["id"], spoon)
    assert found.buy
    assert "points are spent" in found.note
    assert "could not be looked up" in found.note
    assert len(found.unknown) == 1


@pytest.mark.database
def test_a_service_that_cannot_be_reached_is_said_plainly(db):
    stock(db)
    row = a_week(db)
    found = groceries.for_plan(db, row["id"],
                               Dishes(error=client.SpoonacularError("no route")))
    assert found.empty
    assert "could not be reached" in found.note


# --- the line in docs/db.md ----------------------------------------------

def counts(db):
    """Every table's row count, which is what a list may not change."""
    tables = db.execute(
        "select table_name from information_schema.tables"
        " where table_schema = current_schema()").fetchall()
    return {row["table_name"]: db.execute(
        "select count(*) as n from " + row["table_name"]).fetchone()["n"] for row in tables}


@pytest.mark.database
def test_making_a_list_writes_nothing_down(db):
    stock(db)
    row = a_week(db)
    before = counts(db)
    found = groceries.for_plan(db, row["id"], Dishes())
    assert found.buy
    # The list is a function of the plan and the pantry, computed and dropped.
    # There is no grocery_line table under it for the same reason there is no
    # recipe table: a row would be the service's words in a table.
    assert counts(db) == before


@pytest.mark.database
def test_nothing_the_service_wrote_reaches_a_table(db):
    stock(db)
    row = a_week(db)
    # 'fictional saffron' is in 9002's lines and in nothing the household
    # typed, so finding it anywhere is the line being crossed.
    groceries.for_plan(db, row["id"], Dishes())
    written = []
    for table in counts(db):
        for stored in db.execute("select * from " + table).fetchall():
            written.extend(str(value).lower() for value in stored.values() if value is not None)
    assert "fictional" not in " ".join(written)


# --- the board's two views ------------------------------------------------

@pytest.mark.database
def test_the_week_shows_seven_days_both_slots_and_what_fills_them(db):
    stock(db)
    a_week(db)
    page = plan_pages.week_page(db, {}, today=MONDAY)
    assert "monday 21 september" in page
    # Seven days, whatever the plan holds rows for: a week that showed two
    # days because a row went missing would be a week nobody could question.
    assert "sunday 27 september" in page
    assert page.count("<tr>") == 8
    assert "<th>lunch</th><th>dinner</th>" in page
    # Escaped because everything that reaches the HTML is, the board's own
    # prose included: one escaper with no exceptions is the only kind that
    # stays true (board/pages.py).
    assert "the second serving of monday&#x27;s dinner" in page
    # A slot the plan holds nothing for is shown as an empty slot and not
    # left out, which is the whole reason the row exists.
    assert plan_pages.NOTHING in page


@pytest.mark.database
def test_a_skipped_meal_reads_as_skipped(db):
    stock(db)
    row = a_week(db)
    week.skip(db, meals_of(db, row["id"])[(MONDAY, "lunch")]["id"])
    assert "skipped" in plan_pages.week_page(db, {}, today=MONDAY)


@pytest.mark.database
def test_the_week_costs_nothing_to_look_at_until_the_list_is_asked_for(db):
    stock(db)
    a_week(db)
    page = plan_pages.week_page(db, {}, today=MONDAY)
    assert "make the list" in page
    assert "2 lookups" in page
    # Nothing was bought, asked about or listed, because nothing was fetched.
    assert "notional chickpeas" not in page


@pytest.mark.database
def test_the_list_beside_the_week_says_what_is_shared_and_what_is_not(db, monkeypatch):
    stock(db)
    a_week(db)
    monkeypatch.setattr(groceries, "Spoonacular", lambda **kwargs: Dishes())
    page = plan_pages.week_page(db, {"list": ["1"]}, today=MONDAY)
    assert "notional chickpeas" in page
    assert "canned and jarred" in page
    assert plan_pages.ALONE in page
    assert "what the house already has" in page


@pytest.mark.database
def test_the_list_on_its_own_is_the_page_that_goes_to_the_shop(db, monkeypatch):
    stock(db)
    a_week(db)
    monkeypatch.setattr(groceries, "Spoonacular", lambda **kwargs: Dishes())
    page = plan_pages.groceries_page(db, {}, today=MONDAY)
    assert "<h1>the list</h1>" in page
    assert "the week this is for" in page
    assert "notional chickpeas" in page


@pytest.mark.database
def test_an_unplanned_week_is_a_page_and_not_a_failure(db):
    assert "no week is planned yet" in plan_pages.week_page(db, {}, today=MONDAY)
    assert "nothing to buy" in plan_pages.groceries_page(db, {}, today=MONDAY)


@pytest.mark.database
def test_a_name_somebody_typed_cannot_become_markup(db, monkeypatch):
    pantry.add_staple(db, "notional <script>alert(1)</script> oil")
    a_week(db, meals=(week.Meal(MONDAY, "dinner", 2, week.COOK, 9005),))
    monkeypatch.setattr(groceries, "Spoonacular", lambda **kwargs: Dishes(dishes={
        9005: dish(9005, line("notional <script>alert(1)</script> oil", 2, "tbsp"))}))
    page = plan_pages.groceries_page(db, {}, today=MONDAY)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)" not in page


@pytest.mark.database
def test_the_board_survives_a_database_with_no_schema_yet(db):
    db.execute("drop table plan_meal")
    db.execute("drop table plan")
    assert "no week is planned yet" in plan_pages.week_page(db, {}, today=MONDAY)


@pytest.mark.database
def test_the_routes_are_what_the_router_wires(db):
    assert [route.path for route in plan_pages.ROUTES] == ["/", "/week", "/groceries"]
    assert {route.method for route in plan_pages.ROUTES} == {"GET"}
