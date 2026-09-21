"""The stock ledger: how the pantry tells the truth.

Nothing decrements the pantry when a meal is cooked, increments it when a
shop happens, or records that Tuesday was a takeaway - unless it goes
through here. Three weeks without that and the table describes a kitchen
that does not exist, and every promise built on it is computed against
fiction (pm/backlog.md).

So every move writes `stock_move` and applies its effect to `pantry` in one
transaction. A ledger that can disagree with the balance is worse than no
ledger, because it is believed.

The standing assumption is that an unconfirmed meal did not happen: nothing
here runs off a plan, only off something a person or a confirmed run said.
"""
import datetime
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from db.psql import Row
from kitchen import one_of, pantry

REASONS = ("bought", "cooked", "finished", "discarded", "corrected")

# The two slots a day of this plan has, named here because `eating_history`
# is the column they end up in. planner/week.py reads them from here rather
# than spelling them again (pm/backlog.md: breakfast is out).
LUNCH, DINNER = "lunch", "dinner"
SLOTS = (LUNCH, DINNER)

# The cause rides in `note` behind this tag, and the separator is how the
# tag is read back off. See `_claim`.
TAG = "cause:"
SEPARATOR = " - "

# What each writer mints its causes under. The namespace is flat and
# at-most-once, so one writer claiming another's prefix would spend the key
# that writer needs: the board refuses a form carrying anything but BOARD
# (board/pages.py), the planner keys a meal on MEAL, and the scheduler that
# will key a run on RUN is an item after the MVP (pm/backlog.md).
BOARD, MEAL, RUN = "board:", "plan_meal:", "run:"


@dataclass(frozen=True)
class Used:
    """One ingredient a cook took out of the cupboard.

    This is what crosses board -> planner -> kitchen when a meal is
    confirmed, and it is a type rather than a dict because it crosses two
    package boundaries and every other value that does is one. A name on its
    own is a line nobody knows the amount of, which `cook` also takes as a
    bare string.
    """
    ingredient: str
    quantity: pantry.Quantity = None
    unit: str | None = None


@dataclass(frozen=True)
class Cooked:
    """What recording a meal wrote: the stock that moved, and the eating of it."""
    moves: list[Row]
    history: list[Row]


def _record(cx, reason: str, ingredient: str, quantity: pantry.Quantity = None,
            unit: str | None = None, level: str | None = None,
            shelf_life_days: int | None = None, acquired_on: datetime.date | None = None,
            grade: str | None = None, note: str | None = None,
            cause: str | None = None) -> Row | None:
    """Write a move and apply it, both or neither.

    Every optional argument on the five writers below is keyword-only,
    because their third slot means a quantity in four of them and a note in
    `finished`, and `discarded(cx, "milk", "turned")` would otherwise reach
    `decimal.Decimal("turned")`.

    The five reasons are what can happen to stock: 'bought' puts it in,
    'cooked' takes some out, 'finished' and 'discarded' say it is gone -
    whether it was eaten is the waste figure - and 'corrected' is the person
    overruling the arithmetic.

    Private, because which of these arguments mean anything depends on which
    reason is being written: a level belongs to a correction and a shelf life
    to a shop, and a caller handed all ten has to know the table to know
    which four are its own. The five named moves below are how the module is
    written to, and each of them states the list its own reason reads.

    `cause` names what asked for this move, and naming it makes the move
    at-most-once: see `_claim`. Returns the stock_move row, or None when the
    cause has already been recorded.
    """
    one_of(reason, REASONS, "reason")
    if cause is not None:
        _tag(cause)              # checked before anything is opened or written
    with cx.transaction():
        if cause is not None and not _claim(cx, cause):
            return None
        return _write(cx, reason, ingredient, quantity, unit, _note(cause, note),
                      level=level, shelf_life_days=shelf_life_days,
                      acquired_on=acquired_on, grade=grade)


def _write(cx, reason: str, ingredient: str, quantity: pantry.Quantity,
           unit: str | None, note: str | None, **balance) -> Row:
    """One move: the balance moved, and the line of ledger that says it was.

    The only insert into `stock_move` in this module. A single move and a
    whole meal cannot share a transaction - one claim covers a meal and
    another covers a move - but the write itself is the same write, and a
    ledger spelled twice is a ledger that grows a third spelling.

    The line is recorded even when the balance had nowhere to put it: cooking
    with something never written down is normal, and the move is the evidence
    that the pantry is missing a row.
    """
    row = _apply(cx, reason, ingredient, quantity, unit, **balance)
    return cx.execute(
        "insert into stock_move (pantry_id, ingredient, quantity, unit, reason, note)"
        " values (%s, %s, %s, %s, %s, %s) returning *",
        (row["id"] if row else None, ingredient.strip(), pantry.amount(quantity), unit,
         reason, note)).fetchone()


def bought(cx, ingredient: str, *, quantity: pantry.Quantity = None, unit: str | None = None,
           shelf_life_days: int | None = None, acquired_on: datetime.date | None = None,
           grade: str | None = None, note: str | None = None,
           cause: str | None = None) -> Row | None:
    """A shop happened.

    `grade` is what the caller already decided a thing is - a form asks, and
    the answer should not be re-inferred from whether an amount came with it.
    Left out, `kitchen.pantry.restock` reads it off the arguments. A first lot
    of a measured perishable with no shelf life is refused; see `restock`.
    """
    return _record(cx, "bought", ingredient, quantity=quantity, unit=unit,
                  shelf_life_days=shelf_life_days, acquired_on=acquired_on,
                  grade=grade, note=note, cause=cause)


def cooked(cx, ingredient: str, *, quantity: pantry.Quantity = None, unit: str | None = None,
           note: str | None = None, cause: str | None = None) -> Row | None:
    """One ingredient was cooked with. A whole meal is `cook` below."""
    return _record(cx, "cooked", ingredient, quantity=quantity, unit=unit,
                  note=note, cause=cause)


def finished(cx, ingredient: str, *, note: str | None = None,
             cause: str | None = None) -> Row | None:
    """It is gone, and it was eaten."""
    return _record(cx, "finished", ingredient, note=note, cause=cause)


def discarded(cx, ingredient: str, *, quantity: pantry.Quantity = None, unit: str | None = None,
              note: str | None = None, cause: str | None = None) -> Row | None:
    """It is gone, and it was thrown away. This is what waste is measured in."""
    return _record(cx, "discarded", ingredient, quantity=quantity, unit=unit,
                  note=note, cause=cause)


def corrected(cx, ingredient: str, *, quantity: pantry.Quantity = None, unit: str | None = None,
              level: str | None = None, shelf_life_days: int | None = None,
              acquired_on: datetime.date | None = None, grade: str | None = None,
              note: str | None = None, cause: str | None = None) -> Row | None:
    """What is actually on the shelf, whatever the arithmetic thinks.

    The shelf life is worth passing for a thing the pantry has never heard
    of, since correcting one of those is writing it down for the first time.
    """
    return _record(cx, "corrected", ingredient, quantity=quantity, unit=unit, level=level,
                  shelf_life_days=shelf_life_days, acquired_on=acquired_on,
                  grade=grade, note=note, cause=cause)


def cook(cx, ingredients: Iterable[str | Used], *, eaten_on: datetime.date | None = None,
         slot: str = "dinner", method: str | None = None, note: str | None = None,
         cause: str | None = None) -> Cooked | None:
    """Record a meal as cooked: the stock out, and a line of history in.

    `ingredients` is a sequence of `Used`, or of bare names where the amounts
    are not known.

    The history is what the variety cooldown reads later. Not "do not repeat
    recipe 4821" but "there has been chicken thigh three times this month",
    which is the household's own record and keeps indefinitely. The recipe is
    not ours to keep (docs/db.md), so the ingredient and the method are
    written and the recipe is not.

    The whole meal is one claim under `cause`, so a retry that died half way
    through does not half-cook it. Returns what was written, or None when the
    meal has already been recorded.
    """
    one_of(slot, SLOTS, "slot")
    if cause is not None:
        _tag(cause)
    eaten_on = eaten_on or datetime.date.today()
    used = [Used(each) if isinstance(each, str) else each for each in ingredients]
    with cx.transaction():
        if cause is not None and not _claim(cx, cause):
            return None
        made, history = [], []
        for each in used:
            made.append(_write(cx, "cooked", each.ingredient, each.quantity,
                               each.unit, _note(cause, note)))
            history.append(cx.execute(
                "insert into eating_history (eaten_on, slot, ingredient, method)"
                " values (%s, %s, %s, %s) returning *",
                (eaten_on, slot, each.ingredient.strip(), method)).fetchone())
        return Cooked(made, history)


def recent(cx, *, limit: int = 50, ingredient: str | None = None) -> list[Row]:
    """The ledger, newest first. The board's history view and the midweek mail
    are both after-MVP items (pm/backlog.md)."""
    if ingredient is None:
        return cx.execute("select * from stock_move order by happened_at desc, id desc limit %s",
                          (limit,)).fetchall()
    return cx.execute(
        "select * from stock_move where lower(ingredient) = lower(%s)"
        " order by happened_at desc, id desc limit %s", (ingredient.strip(), limit)).fetchall()


def caused_by(cx, cause: str) -> list[Row]:
    """Every move a cause has already made: what makes a retry safe."""
    return cx.execute(
        "select * from stock_move where split_part(note, %s, 1) = %s order by id",
        (SEPARATOR, TAG + cause)).fetchall()


def _apply(cx, reason: str, ingredient: str, quantity: pantry.Quantity, unit: str | None,
           level: str | None = None, shelf_life_days: int | None = None,
           acquired_on: datetime.date | None = None,
           grade: str | None = None) -> Row | None:
    """Move the balance the way this reason moves it.

    'discarded' with a quantity is a part of a thing binned and the rest kept;
    without one it is the whole thing, the common case - a bag of salad does
    not go off by the handful.
    """
    if reason == "bought":
        return pantry.restock(cx, ingredient, quantity=quantity, unit=unit,
                              shelf_life_days=shelf_life_days, acquired_on=acquired_on,
                              grade=grade)
    if reason == "cooked":
        return pantry.subtract(cx, ingredient, quantity=quantity, unit=unit)
    if reason == "finished":
        return pantry.empty(cx, ingredient)
    if reason == "discarded":
        if quantity is None:
            return pantry.empty(cx, ingredient)
        return pantry.subtract(cx, ingredient, quantity=quantity, unit=unit)
    # A correction about a thing that was never written down is a thing being
    # written down. That is how the pantry fills as the board is used.
    row = pantry.correct(cx, ingredient, quantity=quantity, unit=unit, level=level,
                         grade=grade)
    if row is None:
        row = pantry.restock(cx, ingredient, quantity=quantity, unit=unit,
                             shelf_life_days=shelf_life_days, acquired_on=acquired_on,
                             grade=grade)
    return row


def _claim(cx, cause: str) -> bool:
    """Take a cause at most once. True when this call is the one that got it.

    The scheduler retries. A run that died between the API call and the commit
    is run again for the same period, and a laptop waking on Monday may reach
    for a week that is already done (pm/backlog.md). A retry that decrements
    the pantry a second time is exactly the fiction this module exists to
    prevent, so a caller that can name what asked for a move - 'plan_meal:184',
    'run:plan_week:2026-W39' - gets it applied once however often it asks.

    stock_move has no cause column, so the cause rides in `note` behind a tag
    and the check is a lock and a look rather than a unique index. The lock is
    what makes it honest: two schedulers racing would otherwise both look,
    both find nothing and both move the stock. An advisory lock is held to the
    end of the transaction, so the second waits for the first to commit and
    then sees its row. A `cause text unique` column would make all of this one
    insert, and is worth adding whenever a migration next goes in.
    """
    cx.execute("select pg_advisory_xact_lock(%s)", (_lock_key(cause),))
    seen = cx.execute(
        "select id from stock_move where split_part(note, %s, 1) = %s limit 1",
        (SEPARATOR, _tag(cause))).fetchone()
    return seen is None


def _tag(cause: str) -> str:
    """The cause as it appears in a note."""
    if SEPARATOR in cause:
        raise ValueError("a cause may not contain %r: it separates the tag from the note"
                         % SEPARATOR)
    return TAG + cause


def _note(cause: str | None, note: str | None) -> str | None:
    """A note with its cause in front, so the ledger says what asked for it."""
    if cause is None:
        return note
    return _tag(cause) if note is None else _tag(cause) + SEPARATOR + note


def _lock_key(cause: str) -> int:
    """A cause as the bigint an advisory lock wants.

    Hashed in Python rather than by the database, so the key is the same
    number in every process and version that ever asks for it.
    """
    return int.from_bytes(hashlib.sha256(cause.encode("utf-8")).digest()[:8], "big", signed=True)
