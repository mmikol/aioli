"""The fixtures: that they are invented, that they are the right shape, and -
on demand only - that the shape is still the service's.

The contract test is the whole point of the fixtures being hand-written. It
compares keys and types, never values, so the live answer is read and dropped
and nothing of it is written to disk, a log or an assertion message.
"""
import json
import os

import pytest

from recipes import client
from tests.recipes import fixtures

FIXTURES = (fixtures.COMPLEX_SEARCH, fixtures.COMPLEX_SEARCH_WITH_NUTRITION,
            fixtures.FIND_BY_INGREDIENTS, fixtures.INFORMATION)

# CI has no key and must not spend points; the contract test is a thing run by
# hand when the service is suspected of having moved.
IN_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
HAS_KEY = bool(os.environ.get("SPOONACULAR_KEY"))


@pytest.mark.parametrize("fixture", FIXTURES)
def test_the_fixtures_are_nobody_s_recipes(fixture):
    # The guard against someone pasting in a real response: every word a recipe
    # authors carries one of our markers, and a recorded one would carry none.
    for text in fixtures.invented_text(fixture):
        assert any(marker in text.lower() for marker in fixtures.SYNTHETIC_MARKERS), text


def test_a_search_result_carries_used_missed_and_unused():
    first = fixtures.COMPLEX_SEARCH["results"][0]
    assert first["usedIngredients"] and first["missedIngredients"] and first["unusedIngredients"]
    assert first["usedIngredientCount"] == len(first["usedIngredients"])
    assert first["missedIngredientCount"] == len(first["missedIngredients"])
    assert fixtures.COMPLEX_SEARCH["totalResults"] >= len(fixtures.COMPLEX_SEARCH["results"])


def test_a_search_with_nutrition_carries_the_numbers_the_board_shows():
    nutrients = fixtures.COMPLEX_SEARCH_WITH_NUTRITION["results"][0]["nutrition"]["nutrients"]
    assert {n["name"] for n in nutrients} >= {"Calories", "Protein"}


def test_find_by_ingredients_answers_with_a_bare_list():
    # Not an envelope, which is the difference the client's point arithmetic
    # and every caller has to know about.
    assert isinstance(fixtures.FIND_BY_INGREDIENTS, list)
    assert fixtures.FIND_BY_INGREDIENTS[0]["usedIngredients"]


def test_information_carries_the_method_and_the_ready_time():
    assert fixtures.INFORMATION["instructions"].strip()
    assert fixtures.INFORMATION["readyInMinutes"] > 0
    steps = fixtures.INFORMATION["analyzedInstructions"][0]["steps"]
    assert [step["number"] for step in steps] == [1, 2]
    assert fixtures.INFORMATION["extendedIngredients"]


def test_the_quota_error_is_a_402_urllib_can_raise():
    error = fixtures.quota_exhausted_error()
    assert error.code == 402
    assert json.loads(error.read().decode("utf-8")) == fixtures.QUOTA_EXHAUSTED


def test_a_fixture_matches_itself():
    for fixture in FIXTURES:
        assert fixtures.shape_errors(fixture, fixture) == []


def test_the_comparator_notices_a_renamed_field():
    live = json.loads(json.dumps(fixtures.COMPLEX_SEARCH))
    live["results"][0]["usedIngredient"] = live["results"][0].pop("usedIngredients")
    complaints = fixtures.shape_errors(fixtures.COMPLEX_SEARCH, live)
    assert complaints == ["$.results[0].usedIngredients: missing"]


def test_the_comparator_notices_a_retyped_field():
    live = json.loads(json.dumps(fixtures.INFORMATION))
    live["readyInMinutes"] = "35 minutes"
    assert fixtures.shape_errors(fixtures.INFORMATION, live) == [
        "$.readyInMinutes: expected a number, got str"]


def test_the_comparator_lets_the_service_add_things():
    # Extra fields are how an API stays compatible; failing on them would make
    # the contract test cry wolf every release.
    live = json.loads(json.dumps(fixtures.INFORMATION))
    live["newFangledScore"] = 7
    assert fixtures.shape_errors(fixtures.INFORMATION, live) == []


def test_the_comparator_forgives_a_null_and_an_empty_list():
    live = json.loads(json.dumps(fixtures.INFORMATION))
    live["instructions"] = None
    live["extendedIngredients"] = []
    assert fixtures.shape_errors(fixtures.INFORMATION, live) == []


@pytest.mark.contract
@pytest.mark.skipif(not HAS_KEY, reason="no SPOONACULAR_KEY; run this one by hand")
@pytest.mark.skipif(IN_CI, reason="CI has no key and may not spend points")
def test_the_live_shapes_still_match_the_fixtures():
    """Three calls to the real service, about three points, run on demand.

    It asserts on shapes and never on values, so nothing the service authored
    is kept even for the length of a failure message.
    """
    chef = client.Spoonacular()

    search = chef.complex_search(include_ingredients=["chickpeas"], number=2)
    assert search["results"], "the search matched nothing, so it says nothing about the shape"
    assert fixtures.shape_errors(fixtures.COMPLEX_SEARCH, search) == []

    found = chef.find_by_ingredients(["chickpeas", "lemon"], number=2)
    assert found, "nothing came back, so there is no shape to check"
    assert fixtures.shape_errors(fixtures.FIND_BY_INGREDIENTS, found) == []

    method = chef.information(search["results"][0]["id"])
    assert fixtures.shape_errors(fixtures.INFORMATION, method) == []
