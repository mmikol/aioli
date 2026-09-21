"""The join, and the questions it asks rather than the guesses it does not."""
import pytest

from matching.ingredients import (
    CONFIDENT,
    UNCONFIRMED,
    Alias,
    PantryItem,
    RecipeIngredient,
    alias_index,
    alias_key,
    cover,
    normalise_name,
    remember,
    resolve,
)
from matching.units import Conversion

CUPBOARD = [
    PantryItem("tomatoes, tinned", 800, "g"),
    PantryItem("onion", 3, "piece"),
    PantryItem("garlic", 40, "g"),
    PantryItem("plain flour", grade="staple", level="in_stock"),
    PantryItem("olive oil", grade="staple", level="out"),
]

NAMES = [item.ingredient for item in CUPBOARD]


@pytest.mark.parametrize("wording,name", [
    ("2 cups diced tomatoes", "tomato"),
    ("Tomatoes, diced", "tomato"),
    ("1 large onion, finely chopped", "onion"),
    ("3 cloves garlic, minced", "garlic"),
    ("1/2 cup all-purpose flour", "all purpose flour"),
    ("fresh basil leaves", "basil leaf"),
    ("salt to taste", "salt"),
    ("2 large eggs", "egg"),
    ("400 g chopped tomatoes (drained)", "tomato"),
    ("Extra Virgin Olive Oil", "olive oil"),
    ("potatoes", "potato"),
    ("strawberries", "strawberry"),
])
def test_a_wording_reduces_to_the_thing_itself(wording, name):
    assert normalise_name(wording) == name


def test_a_phrase_of_pure_preparation_does_not_vanish():
    # An empty name would match everything, which is worse than a bad name.
    assert normalise_name("finely chopped") == "finely chopped"
    assert normalise_name("") == ""


def test_both_sides_are_reduced_the_same_way():
    assert normalise_name("2 cups diced tomatoes") == normalise_name("Fresh Tomatoes")


def test_an_alias_key_keeps_none_of_the_recipe_s_words():
    # The line in docs/db.md: the wording is the service's text, so what is
    # stored is a digest of it and nothing that can be read back.
    key = alias_key("2 cups diced tomatoes")
    assert len(key) == 64
    assert all(character in "0123456789abcdef" for character in key)
    for word in ("cup", "diced", "tomato"):
        assert word not in key


def test_one_wording_and_its_variants_land_on_one_key():
    assert alias_key("2 cups diced tomatoes") == alias_key("Tomatoes, diced")
    assert alias_key("diced tomatoes") != alias_key("diced onions")


def test_an_alias_is_built_from_a_confirmation():
    written = remember("2 cups diced tomatoes", "tomatoes, tinned")
    assert written.ingredient == "tomatoes, tinned"
    assert written.confirmed is True
    assert written.wording_key == alias_key("diced tomatoes")


def test_rows_from_the_table_index_the_way_resolve_reads_them():
    rows = [{"wording_key": alias_key("passata"), "ingredient": "tomatoes, tinned",
             "confirmed": False}]
    index = alias_index(rows)
    assert index[alias_key("passata")] == Alias(alias_key("passata"), "tomatoes, tinned", False)


def test_a_name_the_house_already_uses_is_certain():
    match = resolve("Onions", NAMES)
    assert match.ingredient == "onion"
    assert match.confidence == 1.0
    assert match.source == "exact"
    assert match.settled


def test_a_confirmed_alias_is_certain_and_a_fresh_one_is_not():
    confirmed = alias_index([remember("2 cups diced tomatoes", "tomatoes, tinned")])
    match = resolve("2 cups diced tomatoes", NAMES, confirmed)
    assert match.ingredient == "tomatoes, tinned"
    assert match.confidence == 1.0
    assert not match.needs_confirmation

    guessed = alias_index([remember("passata", "tomatoes, tinned", confirmed=False)])
    match = resolve("passata", NAMES, guessed)
    assert match.ingredient == "tomatoes, tinned"
    assert match.confidence == UNCONFIRMED
    assert match.needs_confirmation


def test_a_fuzzy_match_carries_its_candidates_and_asks():
    match = resolve("diced tomatoes", NAMES)
    assert match.source == "fuzzy"
    assert match.ingredient == "tomatoes, tinned"
    assert 0 < match.confidence < CONFIDENT
    assert match.needs_confirmation
    assert match.candidates[0][0] == "tomatoes, tinned"
    assert len(match.candidates) <= 3


def test_a_near_spelling_is_not_worth_a_question():
    match = resolve("onions", ["onion", "garlic"])
    assert match.settled


def test_a_wording_with_no_likeness_resolves_to_nothing():
    match = resolve("star anise", NAMES)
    assert match.ingredient is None
    assert match.confidence == 0.0
    assert match.source == "none"
    # The near misses ride along so the question has something under it.
    assert match.candidates


def test_an_empty_pantry_resolves_to_nothing_rather_than_failing():
    assert resolve("onion", []).ingredient is None


def test_enough_in_the_cupboard_is_covered():
    found = cover(
        [RecipeIngredient("tinned tomatoes", 400, "g")],
        CUPBOARD,
        aliases=alias_index([remember("tinned tomatoes", "tomatoes, tinned")]))
    assert not found.missing and not found.uncertain
    line = found.covered[0]
    assert line.ingredient == "tomatoes, tinned"
    assert line.have == pytest.approx(800)
    assert line.short == 0.0
    assert found.complete


def test_too_little_is_missing_by_the_difference():
    found = cover(
        [RecipeIngredient("tinned tomatoes", 1.2, "kg")],
        CUPBOARD,
        aliases=alias_index([remember("tinned tomatoes", "tomatoes, tinned")]))
    line = found.missing[0]
    assert line.unit == "kg"
    assert line.have == pytest.approx(0.8)
    assert line.short == pytest.approx(0.4)
    assert not found.complete


def test_several_rows_of_one_ingredient_add_up():
    pantry = [PantryItem("garlic", 40, "g"), PantryItem("garlic", 0.06, "kg")]
    found = cover([RecipeIngredient("garlic", 90, "g")], pantry)
    assert found.covered[0].have == pytest.approx(100)


def test_a_staple_answers_in_stock_or_out_and_not_in_grams():
    found = cover(
        [RecipeIngredient("plain flour", 2, "cups"),
         RecipeIngredient("olive oil", 2, "tbsp")],
        CUPBOARD)
    assert [line.ingredient for line in found.covered] == ["plain flour"]
    assert [line.ingredient for line in found.missing] == ["olive oil"]
    assert found.covered[0].have is None


def test_a_volume_against_a_mass_asks_instead_of_guessing():
    found = cover([RecipeIngredient("tomatoes, tinned", 2, "cups")], CUPBOARD)
    assert not found.covered and not found.missing
    line = found.uncertain[0]
    assert "tomatoes, tinned" in line.reason


def test_a_density_the_household_has_recorded_settles_it():
    rows = [Conversion("cup", "g", 240.0, ingredient="tomatoes, tinned")]
    found = cover([RecipeIngredient("tomatoes, tinned", 2, "cups")], CUPBOARD,
                  conversions=rows)
    assert found.covered[0].have == pytest.approx(800 / 240)


def test_a_wording_the_cupboard_does_not_resemble_is_bought():
    # Not a question: an empty pantry would otherwise be a page of them.
    found = cover([RecipeIngredient("star anise", 2, "pieces")], CUPBOARD)
    assert not found.uncertain
    line = found.missing[0]
    assert line.ingredient is None
    assert line.short == pytest.approx(2)
    assert not found.complete


def test_an_uncertain_match_is_never_subtracted_quietly():
    found = cover([RecipeIngredient("diced tomatoes", 400, "g")], CUPBOARD)
    assert not found.covered and not found.missing
    assert found.uncertain[0].match.candidates[0][0] == "tomatoes, tinned"


def test_a_line_with_no_amount_is_covered_by_presence():
    found = cover([RecipeIngredient("onion")], CUPBOARD)
    line = found.covered[0]
    assert line.quantity is None
    assert "no amount" in line.reason


def test_an_unknown_unit_is_a_question():
    found = cover([RecipeIngredient("onion", 2, "dollops")], CUPBOARD)
    assert "dollops" in found.uncertain[0].reason


def test_every_line_lands_in_exactly_one_list():
    needs = [
        RecipeIngredient("onion", 1, ""),
        RecipeIngredient("olive oil", 2, "tbsp"),
        RecipeIngredient("star anise", 1, "piece"),
        RecipeIngredient("diced tomatoes", 400, "g"),
    ]
    found = cover(needs, CUPBOARD)
    landed = [line.wording for line in found.covered + found.missing + found.uncertain]
    assert sorted(landed) == sorted(need.wording for need in needs)


@pytest.mark.database
def test_the_tables_hold_what_the_matcher_writes(db):
    import psycopg

    key = alias_key("2 cups diced tomatoes")
    db.execute("insert into ingredient_alias (wording_key, ingredient, confidence,"
               " method, confirmed, confirmed_at)"
               " values (%s, %s, %s, 'manual', true, now())",
               (key, "tomatoes, tinned", 0.63))
    row = db.execute("select ingredient, confirmed from ingredient_alias"
                     " where wording_key = %s", (key,)).fetchone()
    assert row["ingredient"] == "tomatoes, tinned"
    assert row["confirmed"] is True

    db.execute("insert into unit_conversion (ingredient, from_unit, to_unit, factor)"
               " values ('tomatoes, tinned', 'cup', 'g', 240)")
    db.execute("insert into unit_conversion (from_unit, to_unit, factor)"
               " values ('can', 'g', 400)")
    # One factor per ingredient and pair: a second row is a correction and
    # not another opinion, and the general rule is under the same constraint.
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        db.execute("insert into unit_conversion (ingredient, from_unit, to_unit, factor)"
                   " values ('tomatoes, tinned', 'cup', 'g', 250)")


@pytest.mark.database
def test_an_alias_nobody_confirmed_says_so(db):
    # The matcher writes its guesses down so the same question is not asked
    # twice, and an unconfirmed row is still a guess.
    db.execute("insert into ingredient_alias (wording_key, ingredient, confidence)"
               " values (%s, %s, %s)", (alias_key("passata"), "tomatoes, tinned", 0.6))
    row = db.execute("select confirmed, method, times_seen, confirmed_at"
                     " from ingredient_alias where wording_key = %s",
                     (alias_key("passata"),)).fetchone()
    assert row["confirmed"] is False
    assert row["confirmed_at"] is None
    assert row["method"] == "fuzzy"
    assert row["times_seen"] == 1
