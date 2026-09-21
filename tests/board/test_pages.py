"""The three views a person edits: that they say what is true, that they write
through the ledger, that a double tap moves the stock once, and that nothing
rendered here is anybody's words but the household's."""
import datetime
import decimal

import pytest

from board import chrome, pages, serve
from kitchen import moves, pantry, settings
from recipes import client, steps
from tests.recipes import fixtures

TODAY = datetime.date(2026, 9, 20)


class Chef:
    """As much of recipes.client.Spoonacular as the stove calls.

    It records what a call cost the way the real client does, because half of
    what is asserted below is that the ledger hears about a point spent at the
    pan. Every word it answers with is invented next door in recipes/fixtures.
    """

    def __init__(self, payload=None, error=None):
        self.payload = fixtures.INFORMATION if payload is None else payload
        self.error = error
        self.usage = None
        self.asked = []

    def information(self, recipe_id, *, nutrition=False):
        self.asked.append(recipe_id)
        if self.usage is not None:
            self.usage(0.0 if self.error is not None else 1.01, 1)
        if self.error is not None:
            raise self.error
        return self.payload


def _stove(monkeypatch, payload=None, error=None):
    """The board's stove, wired to a chef that has never been near the service.

    The client is replaced rather than handed in, because the recorder the
    stove binds to its own client is the thing under test: a point spent
    while somebody is standing at the pan has to reach `api_usage`.
    """
    chef = Chef(payload, error)

    def built(usage=None, **rest):
        chef.usage = usage
        return chef

    monkeypatch.setattr(steps, "Spoonacular", built)
    monkeypatch.setattr(pages, "STOVE", steps.Stove())
    return chef


def _cooking(db):
    """A pantry holding what the invented method asks for."""
    pantry.add_perishable(db, "notional chickpeas", 2, "can", 30, acquired_on=TODAY)
    pantry.add_staple(db, "pretend olive oil")


def _q(**fields):
    """A query as the router hands it over: a name to a list of values."""
    return {name: value if isinstance(value, list) else [str(value)]
            for name, value in fields.items()}


def _plan(db, state="live", period="2026-W39", closed_at=None):
    return db.execute(
        "insert into plan (period, starts_on, ends_on, state, closed_at)"
        " values (%s, %s, %s, %s, %s) returning *",
        (period, TODAY - datetime.timedelta(days=3), TODAY + datetime.timedelta(days=3),
         state, closed_at)).fetchone()


def _meal(db, plan, day, slot="dinner", kind="cook", servings=2, **fields):
    row = {"skipped": False, "cooked_at": None, "recipe_id": None, "pairs_with": None}
    row.update(fields)
    return db.execute(
        "insert into plan_meal (plan_id, meal_on, slot, servings, kind, skipped,"
        " cooked_at, recipe_id, pairs_with) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " returning *",
        (plan["id"], day, slot, servings, kind, row["skipped"], row["cooked_at"],
         row["recipe_id"], row["pairs_with"])).fetchone()


# --- what can be told without a database ---------------------------------

def test_a_quantity_reads_the_way_a_person_wrote_it():
    # 2.000 kg of potatoes is a column's precision showing through, not
    # something anybody typed.
    assert chrome.figure(decimal.Decimal("2.000")) == "2"
    assert chrome.figure(decimal.Decimal("0.50")) == "0.5"
    assert chrome.figure(decimal.Decimal("1E+2")) == "100"
    assert chrome.figure(None) == ""


def test_a_date_is_said_the_way_it_is_asked_about():
    assert chrome.said(TODAY, TODAY)[1] == "today"
    assert chrome.said(TODAY - datetime.timedelta(days=1), TODAY)[1] == "yesterday"
    assert chrome.said(TODAY - datetime.timedelta(days=3), TODAY)[1] == "3 days ago"
    assert chrome.said(TODAY, TODAY)[0] == "sunday 20 september"


def test_turning_is_counted_and_never_guessed():
    def row(turns_on):
        return {"turns_on": turns_on}

    assert pages._turns(row(None), TODAY) == "no date"
    assert pages._turns(row(TODAY), TODAY) == "turns today"
    assert pages._turns(row(TODAY + datetime.timedelta(days=1)), TODAY) == "turns tomorrow"
    assert pages._turns(row(TODAY + datetime.timedelta(days=4)), TODAY) == "turns in 4 days"
    assert pages._turns(row(TODAY - datetime.timedelta(days=2)), TODAY) == "turned 2 days ago"


def test_a_marked_state_is_marked_inside_itself():
    # `.row .state` is the more specific rule in board.css, so `soon` on the
    # same element would be overruled and the marking would silently do
    # nothing. It goes inside, which restyles nothing.
    assert chrome.state("turns today", True) == (
        "<span class='state'><span class='soon'>turns today</span></span>")
    assert chrome.state("in stock") == "<span class='state'>in stock</span>"


def test_two_lots_of_a_thing_are_one_line_showing_the_older():
    older = {"id": 2, "ingredient": "Chicken", "turns_on": datetime.date(2026, 9, 21)}
    newer = {"id": 7, "ingredient": "chicken", "turns_on": datetime.date(2026, 9, 28)}
    undated = {"id": 9, "ingredient": "rice", "turns_on": None}
    lines = pages._lots([newer, undated, older])
    assert [(row["id"], count) for row, count in lines] == [(2, 2), (9, 1)]


def test_a_blank_box_and_an_absent_one_are_the_same_absence():
    assert chrome.one(_q(unit="  g "), "unit") == "g"
    assert chrome.one({}, "unit") == ""
    assert chrome.one({}, "grade", "staple") == "staple"
    assert chrome.many(_q(cook_days=["sunday", " ", "wednesday"]), "cook_days") == [
        "sunday", "wednesday"]


def test_a_field_that_will_not_parse_blames_the_field():
    with pytest.raises(ValueError, match="the shelf life"):
        chrome.whole("soon", "the shelf life")
    with pytest.raises(ValueError, match="cannot be less than"):
        chrome.whole("0", "how many the meals are for", 1)
    with pytest.raises(ValueError, match="the quantity"):
        chrome.measure("a bag", "the quantity")
    with pytest.raises(ValueError, match="2026-09-20"):
        chrome.date("last tuesday", "the date it came in")


def test_every_route_is_one_the_board_does_not_already_answer():
    # The router serves /health and a short map of static files before it
    # reaches these, so a page shadowing one of them would be a page nobody
    # could open.
    taken = set(serve.STATIC_FILES) | {"/health"}
    assert not {route.path for route in pages.ROUTES} & taken
    assert len({(route.path, route.method) for route in pages.ROUTES}) == len(pages.ROUTES)
    assert all(callable(route.render) for route in pages.ROUTES)
    assert all(route.method in ("GET", "POST") for route in pages.ROUTES)


@pytest.mark.database
def test_the_grade_the_form_chose_is_the_grade_that_is_booked_in(db):
    # A name the house once held as a perishable and has since finished:
    # adding it back as a staple is the household saying what it is, and the
    # arithmetic re-inferring a perishable from the absence of a quantity
    # would refuse the form with "a perishable is measured".
    spent = pantry.add_perishable(db, "notional rice", 1, "kg", 90, acquired_on=TODAY)
    pantry._update(db, spent["id"], quantity=0)
    pages.pantry_edit(db, _q(do="add", ingredient="notional rice", grade="staple",
                             how="found", cause=pages._cause("pantry")))
    assert pantry.find(db, "notional rice")["grade"] == "staple"


@pytest.mark.database
def test_a_cause_the_board_did_not_mint_is_refused(db):
    # Causes are one flat at-most-once namespace, so a form carrying
    # 'plan_meal:184' would claim the key a confirmation needs and leave that
    # meal marked cooked with nothing taken out of the pantry.
    pantry.add_staple(db, "rice")
    page = pages.pantry_edit(db, _q(ingredient="rice", do="finished",
                                    cause="plan_meal:184"))
    assert "did not come from a form on this board" in page
    assert pantry.find(db, "rice")["level"] == "in_stock"
    assert moves.caused_by(db, "plan_meal:184") == []


@pytest.mark.database
def test_the_board_purges_the_weeks_that_are_over_as_it_starts(db):
    # A recipe id is a pointer on a live row and goes when the period closes
    # (docs/db.md). The clock that would keep that promise is an item after
    # the MVP, so the board does it as it starts and the planner does it as it
    # plans; a week a person can still reach at /?plan=<id> is not a closed one.
    over = db.execute(
        "insert into plan (period, starts_on, ends_on, state)"
        " values ('2020-W02', %s, %s, 'live') returning *",
        (datetime.date(2020, 1, 6), datetime.date(2020, 1, 12))).fetchone()
    _meal(db, over, datetime.date(2020, 1, 7), recipe_id=9001)

    assert serve.purge_passed_plans(db) == 1

    closed = db.execute("select * from plan where id = %s", (over["id"],)).fetchone()
    assert closed["state"] == "closed"
    assert closed["closed_at"] is not None
    assert db.execute("select recipe_id from plan_meal where plan_id = %s",
                      (over["id"],)).fetchone()["recipe_id"] is None


# --- the pantry -----------------------------------------------------------

@pytest.mark.database
def test_the_pantry_shows_what_turns_soonest_first_with_the_days_left(db):
    pantry.add_perishable(db, "milk", 2, "l", 30, acquired_on=TODAY)
    pantry.add_perishable(db, "spinach", 200, "g", 2, acquired_on=TODAY)
    pantry.add_staple(db, "rice")
    pantry.add_staple(db, "olive oil", level="low")
    html = pages.pantry_page(db, {}, today=TODAY)

    assert html.index("spinach") < html.index("milk")
    assert "turns in 2 days" in html
    assert "turns in 30 days" in html
    assert "200 g" in html
    # Only the one about to turn is marked, and the running-low staple is.
    assert "<span class='soon'>turns in 2 days</span>" in html
    assert "<span class='soon'>turns in 30 days</span>" not in html
    assert "<span class='soon'>running low</span>" in html
    assert "in stock" in html


@pytest.mark.database
def test_nothing_the_household_typed_can_reach_the_page_as_markup(db):
    # A pantry holds whatever someone wrote down, and an ingredient called
    # <script> is a thing a person is entitled to write down.
    pantry.add_staple(db, "<script>alert(1)</script>")
    html = pages.pantry_page(db, {}, today=TODAY)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.database
def test_an_empty_pantry_says_so_rather_than_showing_nothing(db):
    html = pages.pantry_page(db, {}, today=TODAY)
    assert "nothing perishable is written down" in html
    assert "no staples are written down" in html


@pytest.mark.database
def test_adding_a_perishable_writes_the_stock_and_the_ledger_together(db):
    pages.pantry_edit(db, _q(do="add", ingredient="spinach", grade="perishable",
                             how="bought", quantity="200", unit="g", shelf_life_days="5",
                             acquired_on=TODAY.isoformat(), cause="board:pantry:aaa"))
    held = pantry.find(db, "spinach")
    assert held["quantity"] == 200
    assert held["acquired_on"] == TODAY
    assert held["shelf_life_days"] == 5
    assert [row["reason"] for row in moves.recent(db)] == ["bought"]


@pytest.mark.database
def test_something_already_in_the_house_is_not_recorded_as_a_shop(db):
    # The difference is the one the waste figure and, later, the spend are
    # read off, so the form asks rather than assuming a shop happened.
    pages.pantry_edit(db, _q(do="add", ingredient="flour", grade="staple", how="found"))
    assert [row["reason"] for row in moves.recent(db)] == ["corrected"]
    assert pantry.find(db, "flour")["level"] == "in_stock"


@pytest.mark.database
def test_a_perishable_found_in_the_house_keeps_the_shelf_life_it_was_given(db):
    # Written down for the first time rather than bought, which still has to
    # reach the pantry with its date: a lot with no shelf life is invisible to
    # the planner it was entered for.
    pages.pantry_edit(db, _q(do="add", ingredient="carrots", grade="perishable",
                             how="found", quantity="500", unit="g", shelf_life_days="21",
                             acquired_on=(TODAY - datetime.timedelta(days=4)).isoformat()))
    held = pantry.find(db, "carrots")
    assert held["shelf_life_days"] == 21
    assert held["acquired_on"] == TODAY - datetime.timedelta(days=4)
    assert [row["reason"] for row in moves.recent(db)] == ["corrected"]
    assert "turns in 17 days" in pages.pantry_page(db, {}, today=TODAY)


@pytest.mark.database
def test_a_perishable_without_a_shelf_life_is_refused_and_says_why(db):
    html = pages.pantry_edit(db, _q(do="add", ingredient="spinach", grade="perishable",
                                    quantity="200", unit="g"))
    assert "wants a shelf life" in html
    # Refused means nothing was written, not half of it.
    assert pantry.find(db, "spinach") is None
    assert moves.recent(db) == []


@pytest.mark.database
def test_finished_and_binned_are_different_words_for_the_same_empty_shelf(db):
    pantry.add_perishable(db, "spinach", 200, "g", 5, acquired_on=TODAY)
    pantry.add_perishable(db, "milk", 2, "l", 7, acquired_on=TODAY)
    pages.pantry_edit(db, _q(do="finished", ingredient="spinach", cause="board:pantry:a"))
    pages.pantry_edit(db, _q(do="discarded", ingredient="milk", cause="board:pantry:b"))
    assert pantry.find(db, "spinach")["quantity"] == 0
    assert pantry.find(db, "milk")["quantity"] == 0
    # Waste is the difference between the two, which is why the board offers
    # both buttons rather than one that says gone.
    assert {row["ingredient"]: row["reason"] for row in moves.recent(db)} == {
        "spinach": "finished", "milk": "discarded"}


@pytest.mark.database
def test_a_correction_is_the_person_winning(db):
    pantry.add_perishable(db, "potatoes", 2, "kg", 30, acquired_on=TODAY)
    pages.pantry_edit(db, _q(do="correct", ingredient="potatoes", quantity="0.75",
                             unit="kg", cause="board:pantry:c"))
    assert pantry.find(db, "potatoes")["quantity"] == decimal.Decimal("0.75")
    assert [row["reason"] for row in moves.recent(db)] == ["corrected"]


@pytest.mark.database
def test_a_staple_is_corrected_by_its_level_and_not_by_a_weight(db):
    pantry.add_staple(db, "rice")
    pages.pantry_edit(db, _q(do="correct", ingredient="rice", level="low",
                             cause="board:pantry:d"))
    assert pantry.find(db, "rice")["level"] == "low"


@pytest.mark.database
def test_a_level_the_pantry_does_not_have_is_answered_with_the_page(db):
    pantry.add_staple(db, "rice")
    html = pages.pantry_edit(db, _q(do="correct", ingredient="rice", level="nearly"))
    assert "a level is one of" in html
    assert pantry.find(db, "rice")["level"] == "in_stock"


@pytest.mark.database
def test_a_thumb_that_lands_twice_moves_the_stock_once(db):
    # The form carries the cause, so the second post of the same form is the
    # same cause and kitchen/moves.py has already claimed it.
    pantry.add_perishable(db, "potatoes", 2, "kg", 30, acquired_on=TODAY)
    twice = _q(do="correct", ingredient="potatoes", quantity="1", unit="kg",
               cause="board:pantry:once")
    pages.pantry_edit(db, twice)
    pages.pantry_edit(db, twice)
    assert len(moves.recent(db)) == 1
    assert pantry.find(db, "potatoes")["quantity"] == 1


@pytest.mark.database
def test_the_pantry_refuses_an_edit_it_has_no_verb_for(db):
    html = pages.pantry_edit(db, _q(do="incinerate", ingredient="rice"))
    assert "the pantry cannot" in html
    assert moves.recent(db) == []


@pytest.mark.database
def test_every_form_on_the_pantry_carries_a_cause_of_its_own(db):
    pantry.add_perishable(db, "spinach", 200, "g", 5, acquired_on=TODAY)
    html = pages.pantry_page(db, {}, today=TODAY)
    causes = [part.split("'")[0] for part in html.split("name='cause' value='")[1:]]
    assert len(causes) == len(set(causes)) >= 3
    assert all(cause.startswith("board:pantry:") for cause in causes)


# --- the settings ---------------------------------------------------------

@pytest.mark.database
def test_a_figure_nobody_has_stated_says_it_is_the_default(db):
    html = pages.settings_page(db, {})
    assert "the default" in html
    assert "typed" not in html
    assert "value='1'" in html                    # the household size


@pytest.mark.database
def test_a_figure_from_another_agent_does_not_look_like_one_somebody_typed(db):
    # The day the accountant sets a budget is a change of source and not a
    # migration, and a board that showed only the number would make that day
    # look like nothing had happened.
    settings.put(db, "household_size", 4, source="agent")
    html = pages.settings_page(db, {})
    assert "<span class='soon'>from another agent</span>" in html
    assert "<span class='state'>typed</span>" not in html


@pytest.mark.database
def test_saving_writes_what_changed_and_leaves_the_rest_on_its_default(db):
    pages.settings_edit(db, _q(do="save", household_size="3",
                               max_ready_minutes_weeknight="45",
                               fields=["household_size", "max_ready_minutes_weeknight"]))
    assert settings.household_size(db) == 3
    assert settings.origin(db, "household_size") == "user"
    # Pressing save must not turn every default into a typed figure, or the
    # source column stops being able to say what the household decided.
    assert settings.origin(db, "max_ready_minutes_weeknight") == "default"


@pytest.mark.database
def test_the_days_are_checkboxes_and_come_back_in_week_order(db):
    pages.settings_edit(db, _q(do="save", cook_days=["wednesday", "sunday"],
                               fields=["cook_days"]))
    assert settings.cook_days(db) == ["wednesday", "sunday"]
    html = pages.settings_page(db, {})
    assert "name='cook_days' value='wednesday' checked" in html
    assert "name='cook_days' value='tuesday' checked" not in html


@pytest.mark.database
def test_half_a_saved_form_is_worse_than_a_rejected_one(db):
    html = pages.settings_edit(db, _q(do="save", household_size="2",
                                      max_ready_minutes_weeknight="soon",
                                      fields=["household_size",
                                              "max_ready_minutes_weeknight"]))
    assert "wants a whole number" in html
    assert settings.stated(db) == []


@pytest.mark.database
def test_a_day_list_that_cannot_be_read_is_shown_rather_than_raised(db):
    # A settings page that fell over on a bad value would be the one page
    # able to fix it.
    settings.put(db, "cook_days", "tuseday", source="agent")
    html = pages.settings_page(db, {})
    assert "cook_days is unreadable" in html


@pytest.mark.database
def test_a_rule_is_added_lifted_and_shown_as_what_the_search_will_send(db):
    pages.settings_edit(db, _q(do="add-rule", kind="intolerance", value="Peanut",
                               note="anaphylaxis"))
    pages.settings_edit(db, _q(do="add-rule", kind="dislike", value="olives"))
    html = pages.settings_page(db, {})
    assert "peanut" in html
    assert "the search sends diet nothing, intolerances peanut, and excludes olives" in html

    pages.settings_edit(db, _q(do="drop-rule", kind="dislike", value="olives"))
    assert [rule["value"] for rule in settings.dietary_rules(db)] == ["peanut"]


@pytest.mark.database
def test_a_pan_that_is_not_here_and_a_pan_nobody_has_mentioned_are_different(db):
    pages.settings_edit(db, _q(do="set-equipment", name="Dutch oven", present="yes"))
    assert settings.has_equipment(db, "dutch oven") is True

    pages.settings_edit(db, _q(do="set-equipment", name="dutch oven"))
    assert settings.has_equipment(db, "dutch oven") is False
    assert settings.missing_equipment(db, ["dutch oven", "pan"]) == ["dutch oven"]
    assert "not here" in pages.settings_page(db, {})

    # Forgetting the row says nothing either way, which lets recipes through
    # again; saying it is absent is what drops them.
    pages.settings_edit(db, _q(do="drop-equipment", name="dutch oven"))
    assert settings.has_equipment(db, "dutch oven") is True
    assert settings.equipment(db) == []


@pytest.mark.database
def test_the_settings_refuse_a_verb_they_do_not_have(db):
    html = pages.settings_edit(db, _q(do="reset"))
    assert "the settings cannot" in html
    assert settings.stated(db) == []


# --- the confirmations ----------------------------------------------------

@pytest.mark.database
def test_with_no_week_the_confirmations_say_so_rather_than_showing_nothing(db):
    html = pages.confirm_page(db, {}, today=TODAY)
    assert "the week is not planned yet" in html
    assert pages.to_confirm(db, TODAY) == []


@pytest.mark.database
def test_only_the_meals_already_behind_are_questions(db):
    plan = _plan(db)
    yesterday = _meal(db, plan, TODAY - datetime.timedelta(days=1))
    today = _meal(db, plan, TODAY, slot="lunch")
    _meal(db, plan, TODAY + datetime.timedelta(days=2))          # thursday, not yet
    _meal(db, plan, TODAY - datetime.timedelta(days=40))         # long past asking
    asked = pages.to_confirm(db, TODAY)
    assert [meal.id for meal in asked] == [yesterday["id"], today["id"]]


@pytest.mark.database
def test_a_meal_already_answered_is_not_asked_about_again(db):
    plan = _plan(db)
    _meal(db, plan, TODAY, cooked_at=datetime.datetime(2026, 9, 20, 19, 0))
    _meal(db, plan, TODAY, slot="lunch", kind=None, servings=0, skipped=True)
    waiting = _meal(db, plan, TODAY - datetime.timedelta(days=1))
    assert [meal.id for meal in pages.to_confirm(db, TODAY)] == [waiting["id"]]


@pytest.mark.database
def test_an_empty_slot_is_not_a_question_with_an_answer(db):
    # A slot nothing fills is still a row, so the board shows an empty
    # Tuesday - but asking whether it was cooked has no true answer.
    plan = _plan(db)
    _meal(db, plan, TODAY, kind=None, servings=0)
    assert pages.to_confirm(db, TODAY) == []
    assert "nothing is waiting on an answer" in pages.confirm_page(db, {}, today=TODAY)


@pytest.mark.database
def test_a_week_that_is_over_or_was_never_filled_is_not_asked_about(db):
    closed = _plan(db, state="closed", period="2026-W38",
                   closed_at=datetime.datetime(2026, 9, 14, 9, 0))
    _meal(db, closed, TODAY - datetime.timedelta(days=7))
    unfilled = _plan(db, state="unfilled", period="2026-W37")
    _meal(db, unfilled, TODAY - datetime.timedelta(days=2))
    assert pages.to_confirm(db, TODAY) == []


@pytest.mark.database
def test_the_confirmation_row_asks_one_question_and_offers_two_answers(db):
    plan = _plan(db)
    meal = _meal(db, plan, TODAY - datetime.timedelta(days=1), servings=2)
    html = pages.confirm_page(db, {}, today=TODAY)
    assert "saturday 19 september" in html
    assert "yesterday" in html
    assert "dinner for 2" in html
    assert "<button class='primary' name='answer' value='cooked'>cooked it</button>" in html
    assert "value='skipped'>did not</button>" in html
    assert "name='meal' value='%d'" % meal["id"] in html


@pytest.mark.database
def test_a_portion_of_an_earlier_cook_is_asked_whether_it_was_eaten(db):
    plan = _plan(db)
    cook = _meal(db, plan, TODAY - datetime.timedelta(days=1))
    _meal(db, plan, TODAY, slot="lunch", kind="leftovers", pairs_with=cook["id"])
    html = pages.confirm_page(db, {}, today=TODAY)
    assert "ate it" in html
    assert "leftovers" in html


@pytest.mark.database
def test_the_recipe_pointer_never_reaches_the_page(db):
    # It is a pointer and not content, and the board re-fetches a meal rather
    # than showing a number nobody can read (docs/db.md).
    plan = _plan(db)
    _meal(db, plan, TODAY, recipe_id=987654)
    assert "987654" not in pages.confirm_page(db, {}, today=TODAY)


@pytest.mark.database
def test_answering_yes_writes_the_answer_to_the_plan(db):
    plan = _plan(db)
    meal = _meal(db, plan, TODAY)
    pages.confirm_answer(db, _q(meal=meal["id"], answer="cooked"))
    answered = db.execute("select * from plan_meal where id = %s", (meal["id"],)).fetchone()
    assert answered["cooked_at"] is not None
    assert pages.to_confirm(db, TODAY) == []


@pytest.mark.database
def test_answering_no_moves_nothing_at_all(db):
    # The pantry already assumes an unconfirmed meal did not happen, so saying
    # so agrees with it rather than correcting it.
    plan = _plan(db)
    meal = _meal(db, plan, TODAY)
    pantry.add_perishable(db, "spinach", 200, "g", 5, acquired_on=TODAY)
    pages.confirm_answer(db, _q(meal=meal["id"], answer="skipped"))
    skipped = db.execute("select * from plan_meal where id = %s", (meal["id"],)).fetchone()
    assert skipped["skipped"] is True
    # Skipping empties the meal rather than hiding it, which is the planner's
    # rule and a constraint in 003: the board hands the answer over rather
    # than writing five columns of somebody else's table.
    assert skipped["kind"] is None
    assert skipped["servings"] == 0
    assert moves.recent(db) == []
    assert pantry.find(db, "spinach")["quantity"] == 200


@pytest.mark.database
def test_a_cook_with_no_pointer_left_is_answered_and_subtracts_nothing(db):
    # A closed week has had its pointers purged and a week planned without a
    # key never had one, so there is nothing to fetch and nothing to subtract.
    # The answer is still worth recording: the question can never be answered
    # any better than this.
    plan = _plan(db)
    meal = _meal(db, plan, TODAY)
    pantry.add_perishable(db, "spinach", 200, "g", 5, acquired_on=TODAY)
    pages.confirm_answer(db, _q(meal=meal["id"], answer="cooked"))
    assert pantry.find(db, "spinach")["quantity"] == 200
    assert moves.recent(db) == []
    assert pages.to_confirm(db, TODAY) == []


@pytest.mark.database
def test_confirming_a_cook_moves_the_stock_its_method_names(db, monkeypatch):
    # The button used to stamp `cooked_at` and move nothing at all, and the
    # meal then dropped out of the confirmations and off the list: nobody was
    # asked again and the kilo of chicken stayed in the pantry for the planner
    # to keep scoring a week around (pm/backlog.md).
    chef = _stove(monkeypatch)
    plan = _plan(db)
    meal = _meal(db, plan, TODAY, recipe_id=9001)
    _cooking(db)

    pages.confirm_answer(db, _q(meal=meal["id"], answer="cooked"))

    assert chef.asked == [9001]
    assert pantry.find(db, "notional chickpeas")["quantity"] == 1
    # A staple is a judgement rather than arithmetic: cooking with one moves
    # it to low and only a person says it is out (kitchen/pantry.py).
    assert pantry.find(db, "pretend olive oil")["level"] == "low"
    eaten = db.execute("select * from eating_history order by id").fetchall()
    assert [row["ingredient"] for row in eaten] == ["notional chickpeas", "pretend olive oil"]
    # How it was cooked is the keeps-well rules' column and nothing here
    # classifies one yet; the recipe's own title is not the answer.
    assert {row["method"] for row in eaten} == {None}
    assert pages.to_confirm(db, TODAY) == []


@pytest.mark.database
def test_the_point_spent_at_the_pan_reaches_the_ledger(db, monkeypatch):
    # The ledger is what a planning run asks before it starts, so a fetch it
    # never heard about is a run told it has a day's quota it has spent.
    _stove(monkeypatch)
    plan = _plan(db)
    meal = _meal(db, plan, TODAY, recipe_id=9001)
    _cooking(db)
    pages.confirm_answer(db, _q(meal=meal["id"], answer="cooked"))
    # The ledger counts whole points and the service charges fractions, so a
    # call rounds up (recipes/client.py).
    assert client.spent_today(db) == 2


@pytest.mark.database
def test_a_cook_whose_method_cannot_be_had_is_not_marked_done(db, monkeypatch):
    # A meal silently marked done is worse than one still being asked about:
    # the stock has not moved and nothing would ever ask again.
    _stove(monkeypatch, error=client.QuotaExhausted("spent", status=402))
    plan = _plan(db)
    meal = _meal(db, plan, TODAY, recipe_id=9001)
    _cooking(db)

    html = pages.confirm_answer(db, _q(meal=meal["id"], answer="cooked"))

    assert "quota is spent" in html
    assert "still waiting on an answer" in html
    assert db.execute("select cooked_at from plan_meal where id = %s",
                      (meal["id"],)).fetchone()["cooked_at"] is None
    assert pantry.find(db, "notional chickpeas")["quantity"] == 2
    assert [each.id for each in pages.to_confirm(db, TODAY)] == [meal["id"]]


@pytest.mark.database
def test_the_same_confirmation_twice_cooks_the_meal_once(db, monkeypatch):
    chef = _stove(monkeypatch)
    plan = _plan(db)
    meal = _meal(db, plan, TODAY, recipe_id=9001)
    _cooking(db)
    twice = _q(meal=meal["id"], answer="cooked")

    pages.confirm_answer(db, twice)
    pages.confirm_answer(db, twice)

    assert pantry.find(db, "notional chickpeas")["quantity"] == 1
    assert len(moves.caused_by(db, "plan_meal:%d" % meal["id"])) == 2
    # The second answer found the method in the hour the stove holds, so it
    # spent no point to say the same thing again.
    assert chef.asked == [9001]


@pytest.mark.database
def test_a_superseded_draft_does_not_ask_about_the_same_dinner_twice(db):
    # 003-the-week.sql permits a draft beside the live plan and `week.save`
    # writes a fresh draft on every run, so two planning runs for one week
    # would ask about every dinner twice - and answering both would move the
    # stock twice, under two different causes.
    live = _plan(db)
    eaten = _meal(db, live, TODAY)
    draft = _plan(db, state="draft")
    _meal(db, draft, TODAY)
    assert [meal.id for meal in pages.to_confirm(db, TODAY)] == [eaten["id"]]


@pytest.mark.database
def test_with_no_live_plan_the_newest_draft_is_the_one_asked_about(db):
    older = _plan(db, state="draft")
    _meal(db, older, TODAY)
    newer = _plan(db, state="draft")
    asked = _meal(db, newer, TODAY)
    assert [meal.id for meal in pages.to_confirm(db, TODAY)] == [asked["id"]]


@pytest.mark.database
def test_an_answer_the_board_does_not_understand_is_answered_with_the_page(db):
    plan = _plan(db)
    meal = _meal(db, plan, TODAY)
    html = pages.confirm_answer(db, _q(meal=meal["id"], answer="maybe"))
    assert "an answer is cooked or skipped" in html
    assert db.execute("select cooked_at from plan_meal where id = %s",
                      (meal["id"],)).fetchone()["cooked_at"] is None


@pytest.mark.database
def test_a_board_ahead_of_its_database_still_opens(db):
    # The one view a phone opens should not be the one that falls over when
    # the image and the database disagree; the healthcheck is what says so.
    db.execute("drop table plan_meal")
    assert pages.to_confirm(db, TODAY) == []
    assert "the week is not planned yet" in pages.confirm_page(db, {}, today=TODAY)


@pytest.mark.database
def test_the_answer_a_phone_sent_twice_is_the_planner_s_to_make_harmless(db):
    # Every other form on the board carries a cause of its own; this one does
    # not, because planner/week.py keys a meal on itself and a meal is cooked
    # once. A dropped tailnet and a second tap must not cook it twice.
    plan = _plan(db)
    meal = _meal(db, plan, TODAY)
    twice = _q(meal=meal["id"], answer="cooked")
    pages.confirm_answer(db, twice)
    first = db.execute("select cooked_at from plan_meal where id = %s",
                       (meal["id"],)).fetchone()["cooked_at"]
    pages.confirm_answer(db, twice)
    assert db.execute("select cooked_at from plan_meal where id = %s",
                      (meal["id"],)).fetchone()["cooked_at"] == first
    assert "name='cause'" not in pages.confirm_page(db, {}, today=TODAY)


@pytest.mark.database
def test_every_view_renders_a_whole_page_that_links_to_the_others(db):
    here = {pages.pantry_page: "/pantry", pages.settings_page: "/settings",
            pages.confirm_page: "/confirm"}
    for render, path in here.items():
        html = render(db, {})
        assert html.startswith("<!doctype html>")
        assert "<link rel='stylesheet' href='/static/board.css'>" in html
        assert "<script src='/static/board.js'></script>" in html
        assert html.count("<main>") == 1
        # Every other view is one tap away, and the page does not link to
        # itself: a phone has no back button worth using.
        assert "href='%s'" % path not in html
        for other, _ in chrome.NAV:
            assert other == path or "href='%s'" % other in html
