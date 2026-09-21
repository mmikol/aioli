"""The ledger: that every move lands in both tables or neither, that a meal
leaves a history to read, and that a retry does not cook a meal twice."""
import datetime
import decimal

import pytest

from kitchen import moves, pantry


def test_a_reason_is_checked_before_the_connection_is_touched():
    with pytest.raises(ValueError, match="reason"):
        moves._record(None, "eaten", "rice")


def test_a_cause_may_not_carry_the_separator_that_reads_it_back():
    with pytest.raises(ValueError):
        moves._record(None, "cooked", "rice", cause="plan_meal - 184")


@pytest.mark.database
def test_a_shop_writes_the_move_and_the_stock(db):
    move = moves.bought(db, "spinach", quantity=200, unit="g", shelf_life_days=5)
    assert move["reason"] == "bought"
    assert move["pantry_id"] == pantry.find(db, "spinach")["id"]
    assert pantry.find(db, "spinach")["quantity"] == 200


@pytest.mark.database
def test_cooking_takes_the_stock_out(db):
    pantry.add_perishable(db, "milk", 2, "l", 7)
    pantry.add_staple(db, "rice")
    moves.cooked(db, "milk", quantity=0.5, unit="l")
    moves.cooked(db, "rice")
    assert pantry.find(db, "milk")["quantity"] == decimal.Decimal("1.5")
    assert pantry.find(db, "rice")["level"] == "low"
    assert [row["reason"] for row in moves.recent(db)] == ["cooked", "cooked"]


@pytest.mark.database
def test_finished_and_discarded_both_empty_it_and_say_which(db):
    pantry.add_perishable(db, "spinach", 200, "g", 5)
    pantry.add_perishable(db, "milk", 2, "l", 7)
    moves.finished(db, "spinach")
    moves.discarded(db, "milk", note="turned")
    assert pantry.find(db, "spinach")["quantity"] == 0
    assert pantry.find(db, "milk")["quantity"] == 0
    # Waste is the difference between these two, which is why the reason is
    # kept and not just the fact that the stock went.
    assert {row["ingredient"]: row["reason"] for row in moves.recent(db)} == {
        "spinach": "finished", "milk": "discarded"}


@pytest.mark.database
def test_part_of_a_thing_may_be_thrown_away(db):
    pantry.add_perishable(db, "potatoes", 2, "kg", 30)
    moves.discarded(db, "potatoes", quantity=0.5, unit="kg", note="sprouted")
    assert pantry.find(db, "potatoes")["quantity"] == decimal.Decimal("1.5")


@pytest.mark.database
def test_a_correction_about_an_unrecorded_thing_writes_it_down(db):
    move = moves.corrected(db, "saffron", quantity=2, unit="g", shelf_life_days=900)
    assert move["pantry_id"] is not None
    assert pantry.find(db, "saffron")["quantity"] == 2
    assert moves.corrected(db, "saffron", quantity=1)["reason"] == "corrected"
    assert pantry.find(db, "saffron")["quantity"] == 1


@pytest.mark.database
def test_the_ledger_records_what_the_balance_could_not_hold(db):
    # Cooking with something never written down is normal; the move is the
    # evidence that the pantry is missing a row.
    move = moves.cooked(db, "bay leaf")
    assert move["pantry_id"] is None
    assert move["ingredient"] == "bay leaf"


@pytest.mark.database
def test_a_move_that_fails_moves_neither_table(db):
    pantry.add_perishable(db, "milk", 2, "l", 7)
    with pytest.raises(ValueError):
        moves.cooked(db, "milk", quantity=1, unit="kg")
    assert pantry.find(db, "milk")["quantity"] == 2
    assert moves.recent(db) == []


@pytest.mark.database
def test_a_cause_makes_a_move_happen_once(db):
    # The scheduler retries, and a retry that decrements the pantry twice is
    # exactly the fiction the ledger exists to prevent.
    pantry.add_perishable(db, "milk", 2, "l", 7)
    first = moves.cooked(db, "milk", quantity=0.5, unit="l", cause="plan_meal:184")
    again = moves.cooked(db, "milk", quantity=0.5, unit="l", cause="plan_meal:184")
    assert first is not None
    assert again is None
    assert pantry.find(db, "milk")["quantity"] == decimal.Decimal("1.5")
    assert len(moves.caused_by(db, "plan_meal:184")) == 1


@pytest.mark.database
def test_a_different_cause_is_a_different_move(db):
    pantry.add_staple(db, "rice")
    assert moves.cooked(db, "rice", cause="plan_meal:184") is not None
    assert moves.cooked(db, "rice", cause="plan_meal:185") is not None
    assert len(moves.recent(db)) == 2


@pytest.mark.database
def test_a_cause_keeps_the_note_it_was_given(db):
    move = moves.bought(db, "rice", cause="run:shop:2026-W39", note="on offer")
    assert move["note"] == "cause:run:shop:2026-W39 - on offer"
    assert moves.caused_by(db, "run:shop:2026-W39") == [move]


@pytest.mark.database
def test_a_meal_leaves_the_history_the_cooldown_reads(db):
    pantry.add_perishable(db, "chicken thigh", 2, "lb", 3)
    pantry.add_staple(db, "rice")
    done = moves.cook(db, [moves.Used("chicken thigh", 1, "lb"), "rice"],
                      eaten_on=datetime.date(2026, 9, 20), slot="dinner", method="braised")
    assert pantry.find(db, "chicken thigh")["quantity"] == 1
    assert pantry.find(db, "rice")["level"] == "low"
    assert [(row["ingredient"], row["method"]) for row in done.history] == [
        ("chicken thigh", "braised"), ("rice", "braised")]
    assert [row["reason"] for row in done.moves] == ["cooked", "cooked"]


@pytest.mark.database
def test_a_retried_meal_is_not_half_cooked(db):
    pantry.add_perishable(db, "chicken thigh", 2, "lb", 3)
    first = moves.cook(db, ["chicken thigh"], method="braised", cause="plan_meal:184")
    again = moves.cook(db, ["chicken thigh"], method="braised", cause="plan_meal:184")
    assert first is not None
    assert again is None
    rows = db.execute("select * from eating_history").fetchall()
    assert len(rows) == 1


@pytest.mark.database
def test_a_meal_is_eaten_at_lunch_or_dinner(db):
    with pytest.raises(ValueError):
        moves.cook(db, ["rice"], slot="elevenses")
