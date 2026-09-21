"""The pantry in two grades: what is held, what is nearest turning, and the
two different ways stock comes out."""
import datetime
import decimal

import pytest

from kitchen import pantry

TODAY = datetime.date.today()


def test_a_perishable_without_a_shelf_life_is_refused():
    # Checked before the connection is touched, which is why None does here:
    # a lot with no shelf life never ranks as ageing and is invisible to the
    # planner it was entered for.
    with pytest.raises(ValueError):
        pantry.add_perishable(None, "chicken thigh", 2, "lb", None)


def test_a_quantity_stays_the_quantity_it_was_given():
    assert pantry.amount(0.5) == decimal.Decimal("0.5")
    assert pantry.amount(None) is None


@pytest.mark.database
def test_what_is_in_stock_leaves_out_what_is_gone(db):
    pantry.add_perishable(db, "spinach", 200, "g", 5)
    empty = pantry.add_perishable(db, "milk", 1, "l", 7)
    pantry.update(db, empty["id"], quantity=0)
    pantry.add_staple(db, "rice")
    pantry.add_staple(db, "flour", level="out")
    assert pantry.ingredient_names(db) == ["rice", "spinach"]


@pytest.mark.database
def test_the_names_the_planner_searches_with_are_deduplicated(db):
    pantry.add_perishable(db, "Chicken thigh", 2, "lb", 3)
    pantry.add_perishable(db, "chicken thigh", 1, "lb", 3,
                          acquired_on=TODAY - datetime.timedelta(days=1))
    # Two lots, one search term: which spelling comes back is not worth an
    # opinion, that there is only one of them is.
    assert [name.lower() for name in pantry.ingredient_names(db)] == ["chicken thigh"]
    assert len(pantry.holdings(db, "CHICKEN THIGH")) == 2


@pytest.mark.database
def test_what_is_nearest_turning_comes_first(db):
    pantry.add_perishable(db, "rice pudding", 1, "tub", 30)
    pantry.add_perishable(db, "spinach", 200, "g", 3)
    pantry.add_perishable(db, "beef mince", 500, "g", 10,
                          acquired_on=TODAY - datetime.timedelta(days=8))
    turning = pantry.turning_soonest(db)
    assert [row["ingredient"] for row in turning] == ["beef mince", "spinach", "rice pudding"]
    assert turning[0]["days_left"] == 2
    assert [row["ingredient"] for row in pantry.turning_soonest(db, within_days=3)] == [
        "beef mince", "spinach"]


@pytest.mark.database
def test_a_lot_with_no_date_cannot_be_ranked_so_it_is_not_ranked(db):
    row = pantry.add_perishable(db, "spinach", 200, "g", 3)
    pantry.update(db, row["id"], shelf_life_days=None)
    assert pantry.turning_soonest(db) == []
    assert pantry.ingredient_names(db) == ["spinach"]


@pytest.mark.database
def test_a_perishable_decrements_and_may_land_on_zero(db):
    pantry.add_perishable(db, "milk", 2, "l", 7)
    assert pantry.subtract(db, "milk", 0.5, "l")["quantity"] == decimal.Decimal("1.5")
    assert pantry.subtract(db, "milk", 4, "l")["quantity"] == 0
    assert pantry.ingredient_names(db) == []


@pytest.mark.database
def test_cooking_with_a_staple_marks_it_low_and_never_out(db):
    # Only the person looking at the jar knows it is empty. A planner that
    # decided that for them would leave rice off the list.
    pantry.add_staple(db, "rice")
    assert pantry.subtract(db, "rice")["level"] == "low"
    assert pantry.subtract(db, "rice")["level"] == "low"
    assert pantry.empty(db, "rice")["level"] == "out"


@pytest.mark.database
def test_a_perishable_used_without_an_amount_is_not_guessed_at(db):
    pantry.add_perishable(db, "olive oil", 500, "ml", 365)
    assert pantry.subtract(db, "olive oil")["quantity"] == 500


@pytest.mark.database
def test_a_unit_that_does_not_match_is_not_converted_here(db):
    # The conversion arrives with the ingredient_product table; assuming one
    # would subtract a confident wrong number.
    pantry.add_perishable(db, "milk", 2, "l", 7)
    with pytest.raises(ValueError, match="milk"):
        pantry.subtract(db, "milk", 1, "kg")


@pytest.mark.database
def test_subtracting_something_the_house_does_not_hold_is_not_an_error(db):
    assert pantry.subtract(db, "saffron", 1, "g") is None
    assert pantry.empty(db, "saffron") is None
    assert pantry.correct(db, "saffron", quantity=1) is None


@pytest.mark.database
def test_a_second_lot_keeps_the_older_date(db):
    old = pantry.add_perishable(db, "chicken thigh", 1, "lb", 4,
                                acquired_on=TODAY - datetime.timedelta(days=3))
    new = pantry.restock(db, "chicken thigh", quantity=2, unit="lb")
    assert new["id"] != old["id"]
    assert new["shelf_life_days"] == 4    # inherited: the same chicken as last time
    assert pantry.find(db, "chicken thigh")["id"] == old["id"]


@pytest.mark.database
def test_the_same_lot_arriving_twice_in_a_day_adds_up(db):
    pantry.restock(db, "spinach", quantity=200, unit="g", shelf_life_days=5)
    again = pantry.restock(db, "spinach", quantity=100, unit="g")
    assert again["quantity"] == 300
    assert len(pantry.holdings(db, "spinach")) == 1


@pytest.mark.database
def test_a_staple_comes_back_to_in_stock(db):
    pantry.add_staple(db, "rice", level="out")
    assert pantry.restock(db, "rice")["level"] == "in_stock"
    assert pantry.restock(db, "salt")["grade"] == "staple"
    assert pantry.restock(db, "yoghurt", quantity=500, unit="g",
                          shelf_life_days=14)["grade"] == "perishable"


@pytest.mark.database
def test_a_correction_sets_rather_than_adjusts(db):
    pantry.add_perishable(db, "milk", 2, "l", 7)
    assert pantry.correct(db, "milk", quantity=0.5)["quantity"] == decimal.Decimal("0.5")
    pantry.add_staple(db, "flour")
    assert pantry.correct(db, "flour", level="out")["level"] == "out"


@pytest.mark.database
def test_a_thing_can_change_grade_without_moving(db):
    row = pantry.add_staple(db, "parmesan")
    changed = pantry.update(db, row["id"], grade="perishable", quantity=200, unit="g",
                            acquired_on=TODAY, shelf_life_days=60, level=None)
    assert changed["id"] == row["id"]
    assert changed["grade"] == "perishable"


@pytest.mark.database
def test_a_row_has_only_the_fields_it_has(db):
    row = pantry.add_staple(db, "rice")
    with pytest.raises(ValueError, match="brand"):
        pantry.update(db, row["id"], brand="whatever")


@pytest.mark.database
def test_removing_a_row_says_whether_there_was_one(db):
    row = pantry.add_staple(db, "rice")
    assert pantry.remove(db, row["id"]) is True
    assert pantry.remove(db, row["id"]) is False
    assert pantry.in_stock(db) == []
