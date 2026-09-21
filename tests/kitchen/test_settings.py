"""The household's facts: what answers before anyone has said anything, who
said it when they have, and the three parameters the recipe search takes."""
import datetime

import pytest

from kitchen import settings


def test_a_day_list_comes_back_in_week_order():
    assert settings.days("wednesday, sunday") == ["wednesday", "sunday"]
    assert settings.days("Sunday,sunday, MONDAY") == ["monday", "sunday"]


def test_a_mistyped_day_is_raised_and_not_dropped():
    # Dropping it would plan a week around a cook session nobody scheduled.
    with pytest.raises(ValueError):
        settings.days("tuseday")


def test_every_default_reads_as_what_it_is_for():
    assert int(settings.DEFAULTS["household_size"]) == 1
    assert int(settings.DEFAULTS["max_ready_minutes_weeknight"]) == 45
    assert int(settings.DEFAULTS["max_ready_minutes_weekend"]) == 90
    assert int(settings.DEFAULTS["cook_sessions_per_week"]) == 2
    assert int(settings.DEFAULTS["shop_trips_per_week"]) == 2
    assert settings.days(settings.DEFAULTS["cook_days"])
    assert settings.days(settings.DEFAULTS["shop_days"])


@pytest.mark.database
def test_the_defaults_answer_for_an_empty_table(db):
    assert settings.household_size(db) == 1
    assert settings.max_ready_minutes_weeknight(db) == 45
    assert settings.max_ready_minutes_weekend(db) == 90
    assert settings.cook_sessions_per_week(db) == 2
    assert settings.shop_trips_per_week(db) == 2
    assert settings.stated(db) == []


@pytest.mark.database
def test_a_figure_may_arrive_from_another_agent(db):
    # The day the accountant sets a budget is a change of source and not a
    # migration, so a reader must not care which of the three it was.
    settings.put(db, "household_size", 3, source="agent")
    assert settings.household_size(db) == 3
    assert settings.origin(db, "household_size") == "agent"


@pytest.mark.database
def test_origin_is_default_until_someone_states_it(db):
    assert settings.origin(db, "household_size") == "default"
    settings.put(db, "household_size", 2)
    assert settings.origin(db, "household_size") == "user"


@pytest.mark.database
def test_forgetting_a_fact_puts_it_back_on_its_default(db):
    settings.put(db, "household_size", 4)
    assert settings.forget(db, "household_size") is True
    assert settings.household_size(db) == 1
    assert settings.forget(db, "household_size") is False


@pytest.mark.database
def test_a_source_is_one_of_three(db):
    with pytest.raises(ValueError):
        settings.put(db, "household_size", 2, source="the cat")


@pytest.mark.database
def test_a_setting_that_is_not_a_number_blames_its_key(db):
    settings.put(db, "household_size", "a few")
    with pytest.raises(ValueError, match="household_size"):
        settings.household_size(db)


@pytest.mark.database
def test_the_cadence_is_read_and_not_assumed(db):
    settings.put(db, "cook_days", "Friday, monday")
    assert settings.cook_days(db) == ["monday", "friday"]
    assert settings.shop_days(db) == settings.days(settings.DEFAULTS["shop_days"])


@pytest.mark.database
def test_the_time_cap_follows_the_day(db):
    assert settings.max_ready_minutes(db, datetime.date(2026, 9, 22)) == 45
    assert settings.max_ready_minutes(db, datetime.date(2026, 9, 19)) == 90
    settings.put(db, "max_ready_minutes_weeknight", 30)
    assert settings.max_ready_minutes(db, datetime.date(2026, 9, 22)) == 30


@pytest.mark.database
def test_the_filters_are_shaped_for_the_search(db):
    settings.add_dietary_rule(db, "diet", "Vegetarian")
    settings.add_dietary_rule(db, "intolerance", "peanut")
    settings.add_dietary_rule(db, "dislike", "cilantro")
    settings.add_dietary_rule(db, "dislike", "olives")
    assert settings.recipe_filters(db) == settings.RecipeFilters(
        diet="vegetarian",
        intolerances=["peanut"],
        exclude_ingredients=["cilantro", "olives"])


@pytest.mark.database
def test_a_household_with_nothing_to_avoid_sends_no_diet(db):
    assert settings.recipe_filters(db) == settings.RecipeFilters(
        diet=None, intolerances=[], exclude_ingredients=[])


@pytest.mark.database
def test_stating_a_rule_twice_is_someone_pressing_save(db):
    settings.add_dietary_rule(db, "dislike", "olives")
    settings.add_dietary_rule(db, "dislike", "Olives", note="in a tapenade they are fine")
    rules = settings.dietary_rules(db, kind="dislike")
    assert len(rules) == 1
    assert rules[0]["note"] == "in a tapenade they are fine"
    assert settings.remove_dietary_rule(db, "dislike", "olives") is True
    assert settings.dietary_rules(db) == []


@pytest.mark.database
def test_a_dietary_rule_is_one_of_three_kinds(db):
    with pytest.raises(ValueError):
        settings.add_dietary_rule(db, "allergy", "peanut")


@pytest.mark.database
def test_equipment_nobody_has_mentioned_is_available(db):
    # The other rule would drop every suggestion until someone had typed out
    # their whole kitchen.
    assert settings.has_equipment(db, "saucepan") is True
    settings.add_equipment(db, "Stand mixer", present=False)
    assert settings.has_equipment(db, "stand mixer") is False


@pytest.mark.database
def test_what_is_missing_is_named_and_not_filtered_silently(db):
    settings.add_equipment(db, "dutch oven")
    settings.add_equipment(db, "food processor", present=False)
    assert settings.missing_equipment(
        db, ["dutch oven", "food processor", "wooden spoon"]) == ["food processor"]
    assert [row["name"] for row in settings.equipment(db)] == ["dutch oven", "food processor"]


@pytest.mark.database
def test_removing_a_piece_of_kit_is_not_saying_it_is_absent(db):
    settings.add_equipment(db, "food processor", present=False)
    assert settings.remove_equipment(db, "Food processor") is True
    assert settings.has_equipment(db, "food processor") is True
    assert settings.remove_equipment(db, "food processor") is False
