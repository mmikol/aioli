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

from kitchen import pantry

REASONS = ("bought", "cooked", "finished", "discarded", "corrected")

SLOTS = ("lunch", "dinner")

# The cause rides in `note` behind this tag, and the separator is how the
# tag is read back off. See `_claim`.
TAG = "cause:"
SEPARATOR = " - "


def record(cx, reason, ingredient, quantity=None, unit=None, level=None,
           shelf_life_days=None, acquired_on=None, note=None, cause=None):
    """Write a move and apply it, both or neither.

    The five reasons are what can happen to stock: 'bought' puts it in,
    'cooked' takes some out, 'finished' and 'discarded' say it is gone -
    whether it was eaten is the waste figure - and 'corrected' is the person
    overruling the arithmetic.

    `cause` names what asked for this move, and naming it makes the move
    at-most-once: see `_claim`. Returns the stock_move row, or None when the
    cause has already been recorded.
    """
    if reason not in REASONS:
        raise ValueError("a reason is one of %s, not %r" % (", ".join(REASONS), reason))
    if cause is not None:
        _tag(cause)              # checked before anything is opened or written
    with cx.transaction():
        if cause is not None and not _claim(cx, cause):
            return None
        row = _apply(cx, reason, ingredient, quantity, unit, level,
                     shelf_life_days, acquired_on)
        # The ledger records what happened even when the balance had nowhere
        # to put it - cooking with something never written down is normal, and
        # the move is the evidence that the pantry is missing a row.
        return cx.execute(
            "insert into stock_move (pantry_id, ingredient, quantity, unit, reason, note)"
            " values (%s, %s, %s, %s, %s, %s) returning *",
            (row["id"] if row else None, ingredient.strip(), pantry.amount(quantity), unit,
             reason, _note(cause, note))).fetchone()


def bought(cx, ingredient, quantity=None, unit=None, shelf_life_days=None,
           acquired_on=None, note=None, cause=None):
    """A shop happened."""
    return record(cx, "bought", ingredient, quantity=quantity, unit=unit,
                  shelf_life_days=shelf_life_days, acquired_on=acquired_on,
                  note=note, cause=cause)


def cooked(cx, ingredient, quantity=None, unit=None, note=None, cause=None):
    """One ingredient was cooked with. A whole meal is `cook` below."""
    return record(cx, "cooked", ingredient, quantity=quantity, unit=unit,
                  note=note, cause=cause)


def finished(cx, ingredient, note=None, cause=None):
    """It is gone, and it was eaten."""
    return record(cx, "finished", ingredient, note=note, cause=cause)


def discarded(cx, ingredient, quantity=None, unit=None, note=None, cause=None):
    """It is gone, and it was thrown away. This is what waste is measured in."""
    return record(cx, "discarded", ingredient, quantity=quantity, unit=unit,
                  note=note, cause=cause)


def corrected(cx, ingredient, quantity=None, unit=None, level=None, shelf_life_days=None,
              acquired_on=None, note=None, cause=None):
    """What is actually on the shelf, whatever the arithmetic thinks.

    The shelf life is worth passing for a thing the pantry has never heard
    of, since correcting one of those is writing it down for the first time.
    """
    return record(cx, "corrected", ingredient, quantity=quantity, unit=unit, level=level,
                  shelf_life_days=shelf_life_days, acquired_on=acquired_on,
                  note=note, cause=cause)


def cook(cx, ingredients, eaten_on=None, slot="dinner", method=None, note=None, cause=None):
    """Record a meal as cooked: the stock out, and a line of history in.

    `ingredients` is a sequence of names, or of dicts carrying `ingredient`
    and, where the amounts are known, `quantity` and `unit`.

    The history is what the variety cooldown reads later. Not "do not repeat
    recipe 4821" but "there has been chicken thigh three times this month",
    which is the household's own record and keeps indefinitely. The recipe is
    not ours to keep (docs/db.md), so the ingredient and the method are
    written and the recipe is not.

    The whole meal is one claim under `cause`, so a retry that died half way
    through does not half-cook it. Returns the moves and the history rows, or
    None when the meal has already been recorded.
    """
    if slot not in SLOTS:
        raise ValueError("a slot is one of %s, not %r" % (", ".join(SLOTS), slot))
    if cause is not None:
        _tag(cause)
    eaten_on = eaten_on or datetime.date.today()
    used = [{"ingredient": each} if isinstance(each, str) else dict(each) for each in ingredients]
    with cx.transaction():
        if cause is not None and not _claim(cx, cause):
            return None
        moves, history = [], []
        for each in used:
            name = each["ingredient"]
            row = _apply(cx, "cooked", name, each.get("quantity"), each.get("unit"),
                         None, None, None)
            moves.append(cx.execute(
                "insert into stock_move (pantry_id, ingredient, quantity, unit, reason, note)"
                " values (%s, %s, %s, %s, 'cooked', %s) returning *",
                (row["id"] if row else None, name.strip(), pantry.amount(each.get("quantity")),
                 each.get("unit"), _note(cause, note))).fetchone())
            history.append(cx.execute(
                "insert into eating_history (eaten_on, slot, ingredient, method)"
                " values (%s, %s, %s, %s) returning *",
                (eaten_on, slot, name.strip(), method)).fetchone())
        return {"moves": moves, "history": history}


def recent(cx, limit=50, ingredient=None):
    """The ledger, newest first: what the board shows and the mails read."""
    if ingredient is None:
        return cx.execute("select * from stock_move order by happened_at desc, id desc limit %s",
                          (limit,)).fetchall()
    return cx.execute(
        "select * from stock_move where lower(ingredient) = lower(%s)"
        " order by happened_at desc, id desc limit %s", (ingredient.strip(), limit)).fetchall()


def caused_by(cx, cause):
    """Every move a cause has already made: what makes a retry safe."""
    return cx.execute(
        "select * from stock_move where split_part(note, %s, 1) = %s order by id",
        (SEPARATOR, TAG + cause)).fetchall()


def _apply(cx, reason, ingredient, quantity, unit, level, shelf_life_days, acquired_on):
    """Move the balance the way this reason moves it.

    'discarded' with a quantity is a part of a thing binned and the rest kept;
    without one it is the whole thing, the common case - a bag of salad does
    not go off by the handful.
    """
    if reason == "bought":
        return pantry.restock(cx, ingredient, quantity=quantity, unit=unit,
                              shelf_life_days=shelf_life_days, acquired_on=acquired_on)
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
    row = pantry.correct(cx, ingredient, quantity=quantity, unit=unit, level=level)
    if row is None:
        row = pantry.restock(cx, ingredient, quantity=quantity, unit=unit,
                             shelf_life_days=shelf_life_days, acquired_on=acquired_on)
    return row


def _claim(cx, cause):
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


def _tag(cause):
    """The cause as it appears in a note."""
    if SEPARATOR in cause:
        raise ValueError("a cause may not contain %r: it separates the tag from the note"
                         % SEPARATOR)
    return TAG + cause


def _note(cause, note):
    """A note with its cause in front, so the ledger says what asked for it."""
    if cause is None:
        return note
    return _tag(cause) if note is None else _tag(cause) + SEPARATOR + note


def _lock_key(cause):
    """A cause as the bigint an advisory lock wants.

    Hashed in Python rather than by the database, so the key is the same
    number in every process and version that ever asks for it.
    """
    return int.from_bytes(hashlib.sha256(cause.encode("utf-8")).digest()[:8], "big", signed=True)
