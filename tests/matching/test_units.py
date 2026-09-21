"""The unit arithmetic, which is all definitions and one refusal."""
import pytest

from matching.units import (
    COUNT,
    MASS,
    VOLUME,
    Conversion,
    convert,
    dimension_of,
    normalise_unit,
    parse_quantity,
)


@pytest.mark.parametrize("spelling,canonical", [
    ("cup", "cup"),
    ("cups", "cup"),
    ("c", "cup"),
    ("Cups", "cup"),
    ("tbsp", "tbsp"),
    ("tbsp.", "tbsp"),
    ("Tablespoons", "tbsp"),
    ("tsp", "tsp"),
    ("g", "g"),
    ("gram", "g"),
    ("grams", "g"),
    ("kg", "kg"),
    ("kilograms", "kg"),
    ("oz", "oz"),
    ("ounce", "oz"),
    ("fl. oz.", "floz"),
    ("fluid ounces", "floz"),
    ("ml", "ml"),
    ("millilitres", "ml"),
    ("l", "l"),
    ("liters", "l"),
    ("lb", "lb"),
    ("pounds", "lb"),
    ("cloves", "clove"),
    ("tins", "can"),
    ("leaves", "leaf"),
    ("sprigs", "sprig"),
    ("large", "piece"),
])
def test_a_spelling_reaches_its_canonical_unit(spelling, canonical):
    assert normalise_unit(spelling) == canonical


def test_an_absent_unit_is_a_count():
    # "2 eggs" sends no unit because the egg is the unit.
    assert normalise_unit("") == "piece"
    assert normalise_unit(None) == "piece"


def test_a_word_that_is_not_a_unit_says_so():
    assert normalise_unit("dollop") is None
    assert normalise_unit("tomatoes") is None
    assert dimension_of("dollop") is None


def test_a_unit_knows_what_it_measures():
    assert dimension_of("kg") == MASS
    assert dimension_of("cups") == VOLUME
    assert dimension_of("cloves") == COUNT


@pytest.mark.parametrize("phrase,amount", [
    ("2", 2.0),
    ("2.5", 2.5),
    ("1/2", 0.5),
    ("1 1/2", 1.5),
    ("3/4", 0.75),
    # The escape rather than the character: a vulgar fraction arrives
    # in recipe text often enough to test, and the source stays ASCII.
    ("\u00bd", 0.5),
    ("1\u00bd", 1.5),
    ("2-3", 3.0),
    ("2 to 3", 3.0),
    ("400", 400.0),
    (7, 7.0),
    (1.25, 1.25),
])
def test_an_amount_is_read_from_the_front_of_a_phrase(phrase, amount):
    assert parse_quantity(phrase) == pytest.approx(amount)


def test_a_phrase_with_no_amount_has_none():
    assert parse_quantity("salt") is None
    assert parse_quantity(None) is None
    assert parse_quantity("") is None


def test_a_unit_converts_to_itself_unchanged():
    moved = convert(3, "cups", "cup")
    assert moved and moved.quantity == pytest.approx(3)
    assert moved.basis == "same"


@pytest.mark.parametrize("quantity,source,target,expected", [
    (1, "kg", "g", 1000.0),
    (500, "g", "kg", 0.5),
    (1, "lb", "g", 453.59237),
    (16, "oz", "lb", 1.0),
    (1, "cup", "ml", 236.5882365),
    (1, "tbsp", "tsp", 3.0),
    (1, "l", "ml", 1000.0),
    (2, "pints", "cups", 4.0),
])
def test_definitions_convert_without_being_told_anything(quantity, source, target, expected):
    moved = convert(quantity, source, target)
    assert moved, moved.reason
    assert moved.quantity == pytest.approx(expected)
    assert moved.unit == normalise_unit(target)
    assert moved.basis == "generic"


def test_a_volume_does_not_become_a_mass_by_guessing():
    # The refusal this module exists for: a cup of flour is about 120 g and a
    # cup of honey about 340 g, so a guess is a wrong number in a
    # subtraction nobody downstream can question.
    moved = convert(2, "cups", "g", ingredient="flour")
    assert not moved
    assert moved.quantity is None
    assert "flour" in moved.reason


def test_a_mass_does_not_become_a_volume_by_guessing_either():
    assert not convert(500, "g", "ml")


def test_one_count_is_not_another():
    assert convert(3, "cloves", "cloves")
    assert not convert(3, "cloves", "pieces")
    assert not convert(3, "cloves", "g")


def test_a_density_for_the_ingredient_makes_the_conversion():
    rows = [Conversion("cup", "g", 120.0, ingredient="flour")]
    moved = convert(2, "cups", "g", ingredient="flour", conversions=rows)
    assert moved and moved.quantity == pytest.approx(240.0)
    assert moved.basis == "ingredient"


def test_a_density_answers_in_units_it_was_not_filed_in():
    # Filed as a cup of flour; asked about millilitres and kilograms.
    rows = [Conversion("cup", "g", 120.0, ingredient="flour")]
    moved = convert(236.5882365, "ml", "g", ingredient="flour", conversions=rows)
    assert moved and moved.quantity == pytest.approx(120.0)
    moved = convert(1, "kg", "cups", ingredient="flour", conversions=rows)
    assert moved and moved.quantity == pytest.approx(1000.0 / 120.0)


def test_a_density_filed_against_another_ingredient_is_not_borrowed():
    rows = [Conversion("cup", "g", 340.0, ingredient="honey")]
    assert not convert(1, "cup", "g", ingredient="flour", conversions=rows)


def test_the_ingredient_beats_the_general_rule():
    rows = [
        Conversion("can", "g", 400.0),
        Conversion("can", "g", 800.0, ingredient="tomatoes, tinned"),
    ]
    general = convert(1, "can", "g", ingredient="chickpeas", conversions=rows)
    specific = convert(1, "can", "g", ingredient="tomatoes, tinned", conversions=rows)
    assert general.quantity == pytest.approx(400.0)
    assert general.basis == "table"
    assert specific.quantity == pytest.approx(800.0)
    assert specific.basis == "ingredient"


def test_a_conversion_is_read_backwards_as_well():
    rows = [Conversion("clove", "g", 5.0, ingredient="garlic")]
    moved = convert(40, "g", "cloves", ingredient="garlic", conversions=rows)
    assert moved and moved.quantity == pytest.approx(8.0)


def test_an_unknown_unit_is_refused_by_name():
    refused = convert(1, "dollop", "g")
    assert not refused
    assert "dollop" in refused.reason


def test_nothing_to_convert_is_not_zero():
    refused = convert(None, "g", "kg")
    assert not refused
    assert refused.quantity is None
