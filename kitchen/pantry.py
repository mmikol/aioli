"""What is in the house, in two grades.

A perishable carries a quantity, a unit, the date it came in and a rough
shelf life, because that is where waste happens and where the arithmetic has
to work. A staple carries a level and nothing else: nobody weighs their
rice, and a pantry that asks them to is a pantry abandoned inside a
fortnight (pm/backlog.md).

The grade is a column rather than two tables, so a thing can change grade
without moving. That is also why every function here takes an ingredient and
asks the row what grade it is; the caller never has to know.

Nothing in this module writes to `stock_move`. Moving stock without a ledger
line is how the table starts describing a kitchen that does not exist, so
the pantry is moved through kitchen/moves.py and read through here.
"""
import datetime
import decimal

from db.psql import Row
from kitchen import one_of

PERISHABLE = "perishable"
STAPLE = "staple"
GRADES = (PERISHABLE, STAPLE)

# A staple's whole vocabulary. 'out' is a person's word: see `subtract`.
LEVELS = ("in_stock", "low", "out")

# Every argument with a default on a public function here is keyword-only,
# the way matching/ and recipes/ already write theirs: five sibling writers
# whose third slot means a quantity in four of them and a note in the fifth is
# a mistake nothing catches (kitchen/moves.py).

# The day a perishable turns. Postgres adds an integer to a date as days: the
# whole arithmetic the planner's waste term rests on.
TURNS_ON = "(acquired_on + shelf_life_days)"

FIELDS = ("ingredient", "grade", "quantity", "unit", "acquired_on", "shelf_life_days", "level")

# What a caller may hand over as an amount: a number, the exact decimal a
# column holds, or the text a form sent. `amount` below is what turns any of
# them into the one shape the database takes.
Quantity = float | int | decimal.Decimal | str | None


def amount(value: Quantity) -> decimal.Decimal | None:
    """A quantity as an exact decimal, because every quantity column is numeric.

    A caller hands over whatever a recipe or a form gave it, and half a kilo
    arriving as a float and leaving as 0.49999 is the kind of drift that is
    never noticed and never forgiven. kitchen/moves.py writes quantities too,
    so this is not private to this module.
    """
    if value is None or isinstance(value, decimal.Decimal):
        return value
    return decimal.Decimal(str(value))


def add_perishable(cx, ingredient: str, quantity: Quantity, unit: str | None,
                   shelf_life_days: int | None, *,
                   acquired_on: datetime.date | None = None) -> Row:
    """Book in something that will spoil.

    The shelf life is not optional here although the column allows a null,
    because it is the whole reason a perishable is a perishable: it is what
    makes ageing stock rank ahead of fresh, and a row without it is invisible
    to the planner it was entered for.

    `unit` and `shelf_life_days` are typed as optional and refused when they
    are missing, because `restock` above forwards what a caller had - which
    is often nothing - and a signature that forbade None would be describing
    a check this body makes rather than one the type system does.
    """
    if quantity is None or unit is None:
        raise ValueError("a perishable is measured: %r wants a quantity and a unit" % ingredient)
    if shelf_life_days is None:
        raise ValueError("a perishable wants a shelf life: %r would never rank as ageing"
                         % ingredient)
    return cx.execute(
        "insert into pantry (ingredient, grade, quantity, unit, acquired_on, shelf_life_days)"
        " values (%s, 'perishable', %s, %s, %s, %s) returning *",
        (ingredient.strip(), amount(quantity), unit.strip(),
         acquired_on or datetime.date.today(), shelf_life_days)).fetchone()


def add_staple(cx, ingredient: str, *, level: str = "in_stock") -> Row:
    """Book in something that does not spoil on a schedule."""
    one_of(level, LEVELS, "level")
    return cx.execute(
        "insert into pantry (ingredient, grade, level) values (%s, 'staple', %s) returning *",
        (ingredient.strip(), level)).fetchone()


def find(cx, ingredient: str) -> Row | None:
    """The row holding an ingredient, or None.

    Matched on lower(ingredient), the way the index is. A second lot of the
    same thing is its own row - two chickens bought a week apart turn a week
    apart - and the one nearest turning is the one handed back, so subtracting
    cooks the older stock first.

    The day it turns rides on the row as it does on every other reader here:
    the ordering computes it anyway, and one row shape across the module is
    what lets a caller hand a row from any of them to the same code.
    """
    # The concatenation is TURNS_ON, a constant in this module; the ingredient
    # is a parameter. Nothing a caller supplies reaches the statement.
    return cx.execute(
        "select *, " + TURNS_ON + " as turns_on from pantry"   # nosec B608
        " where lower(ingredient) = lower(%s)"
        " order by " + TURNS_ON + " nulls last, id limit 1", (ingredient.strip(),)).fetchone()


def holdings(cx, ingredient: str) -> list[Row]:
    """Every lot of an ingredient, nearest turning first."""
    return cx.execute(
        "select *, " + TURNS_ON + " as turns_on from pantry"   # nosec B608
        " where lower(ingredient) = lower(%s) order by " + TURNS_ON + " nulls last, id",
        (ingredient.strip(),)).fetchall()


def in_stock(cx) -> list[Row]:
    """What the house actually has.

    A perishable with nothing left is a row waiting to be bought again rather
    than stock, and a staple marked out is the same. Both are kept, because a
    thing the household buys is worth remembering the shelf life of.
    """
    return cx.execute(
        "select *, " + TURNS_ON + " as turns_on from pantry"   # nosec B608
        " where (grade = 'perishable' and coalesce(quantity, 0) > 0)"
        "    or (grade = 'staple' and level <> 'out')"
        " order by lower(ingredient)").fetchall()


def ingredient_names(cx) -> list[str]:
    """The names the planner searches with, deduplicated and in order.

    This is `includeIngredients` on the search: the week is built from what
    is already in the house first and bought for second, so these names go
    out with the query rather than filtering what comes back.

    Two lots of a thing spelled two ways are one search term, and which of
    the spellings is sent is not worth an opinion.
    """
    rows = cx.execute(
        "select min(ingredient) as ingredient from pantry"
        " where (grade = 'perishable' and coalesce(quantity, 0) > 0)"
        "    or (grade = 'staple' and level <> 'out')"
        " group by lower(ingredient) order by lower(ingredient)").fetchall()
    return [row["ingredient"] for row in rows]


def turning_soonest(cx, *, within_days: int | None = None, limit: int | None = None,
                    today: datetime.date | None = None) -> list[Row]:
    """Perishables by the day they turn, soonest first.

    The planner ranks ageing stock ahead of fresh, and the midweek mail that
    will ask about what is nearly gone is an after-MVP item (pm/backlog.md);
    both read this query. A row without
    a date or a shelf life cannot be ranked, so it is not here: `days_left`
    would be a guess, and a guess is what the whole waste figure would then
    be computed from.

    Today is the household's, not the database's. `current_date` is whatever
    timezone the server happens to run in, which on this stack is UTC, so an
    evening west of Greenwich would age every perishable by a day and tell
    someone their spinach turns tomorrow when it turns the day after.
    """
    today = today or datetime.date.today()
    # Built out of TURNS_ON and nothing else; today, the window and the limit
    # are all parameters.
    sql = ("select *, " + TURNS_ON + " as turns_on, "   # nosec B608
           + TURNS_ON + " - %s::date as days_left"
           " from pantry where grade = 'perishable' and coalesce(quantity, 0) > 0"
           " and acquired_on is not null and shelf_life_days is not null")
    args = [today]
    if within_days is not None:
        sql += " and " + TURNS_ON + " - %s::date <= %s"
        args.append(today)
        args.append(within_days)
    sql += " order by turns_on, lower(ingredient)"
    if limit is not None:
        sql += " limit %s"
        args.append(limit)
    return cx.execute(sql, args).fetchall()


def _update(cx, pantry_id: int, **fields) -> Row | None:
    """Set columns on a row by hand.

    Private the way kitchen/moves.py's `_record` is: a bag of columns checked
    at runtime is a reasonable thing to have inside a module and a poor thing
    to advertise. What the board corrects a row with is `moves.corrected`.

    A grade change is a normal edit, not a special case: the point of the
    grade being a column.
    """
    unknown = [name for name in fields if name not in FIELDS]
    if unknown:
        raise ValueError("a pantry row has no %s" % ", ".join(sorted(unknown)))
    if not fields:
        return cx.execute("select * from pantry where id = %s", (pantry_id,)).fetchone()
    names = sorted(fields)
    sets = ", ".join("%s = %%s" % name for name in names) + ", updated_at = now()"
    # Every name in `sets` was checked against FIELDS above and every value is
    # a parameter, so the only thing a caller supplies to the statement itself
    # is a choice of column out of a closed list.
    return cx.execute("update pantry set " + sets + " where id = %s returning *",   # nosec B608
                      [fields[name] for name in names] + [pantry_id]).fetchone()


def remove(cx, pantry_id: int) -> bool:
    """Take a row out. True when there was one.

    The ledger survives it: `stock_move.pantry_id` is set null and the moves
    keep their ingredient, so deleting a row loses the balance and not the
    history of how it got there.
    """
    return cx.execute("delete from pantry where id = %s", (pantry_id,)).rowcount > 0


def restock(cx, ingredient: str, *, quantity: Quantity = None, unit: str | None = None,
            shelf_life_days: int | None = None, acquired_on: datetime.date | None = None,
            grade: str | None = None) -> Row:
    """Put stock in: a shop, or a correction upward.

    A staple comes back to 'in_stock'. A perishable arriving is a new row
    rather than a bigger number on the old one, because two lots bought a
    week apart turn a week apart and adding them together loses the older
    date, the one the planner needs. The same lot arriving twice on one day is
    the exception, and adding is right there.

    An unstated shelf life is inherited from the last lot of the same thing,
    since a household buys the same chicken repeatedly; an unstated grade is
    read off the arguments, because a quantity and a unit are what a
    perishable is.
    """
    ingredient = ingredient.strip()
    held = find(cx, ingredient)
    grade = one_of(_grade_of(held, quantity, unit) if grade is None else grade,
                   GRADES, "grade")

    if grade == STAPLE:
        if held is not None and held["grade"] == STAPLE:
            return _update(cx, held["id"], level="in_stock")
        return add_staple(cx, ingredient)

    acquired_on = acquired_on or datetime.date.today()
    if shelf_life_days is None and held is not None:
        shelf_life_days = held["shelf_life_days"]
    same_lot = cx.execute(
        "select * from pantry where lower(ingredient) = lower(%s) and grade = 'perishable'"
        " and acquired_on = %s and lower(coalesce(unit, '')) = lower(coalesce(%s, ''))"
        " order by id limit 1", (ingredient, acquired_on, unit)).fetchone()
    if same_lot is not None:
        return _update(cx, same_lot["id"],
                      quantity=(same_lot["quantity"] or 0) + (amount(quantity) or 0))
    return add_perishable(cx, ingredient, quantity, unit, shelf_life_days,
                          acquired_on=acquired_on)


def _grade_of(held, quantity: Quantity, unit: str | None) -> str:
    """What grade a thing arriving is, when the caller did not say. `restock`
    above says why it is read this way."""
    if held is not None:
        return held["grade"]
    return PERISHABLE if quantity is not None and unit is not None else STAPLE


def subtract(cx, ingredient: str, *, quantity: Quantity = None,
             unit: str | None = None) -> Row | None:
    """Take stock out. The two grades do not do it the same way.

    A perishable's quantity is arithmetic and may land on zero. A staple's
    level is a judgement, so cooking with one moves it to 'low' at most and
    never to 'out': only the person looking at the jar knows it is empty, and
    a planner that decided that for them would leave rice off the list.
    Saying a thing is gone is `empty` below.

    A perishable used without a quantity is left alone, not guessed at. The
    move is still recorded by the caller, so the drift shows in the ledger
    rather than becoming a number the waste figure is computed from.

    Returns the row as it now stands, or None when the house does not hold the
    thing at all: a fact worth handing back, not raising over, since cooking
    with something unrecorded is normal. Raises ValueError when the unit given
    disagrees with the unit the shelf holds, which is the one case here that
    is a caller's mistake rather than a fact about the kitchen.
    """
    held = find(cx, ingredient)
    if held is None:
        return None
    if held["grade"] == STAPLE:
        return _update(cx, held["id"],
                       level="low" if held["level"] == "in_stock" else held["level"])
    if quantity is None:
        return held
    if unit and held["unit"] and unit.strip().lower() != held["unit"].strip().lower():
        # A recipe's words are not the pantry's words, and neither are its
        # units. The conversion the household supplies is `unit_conversion`,
        # and the caller that holds one applies it before it gets here
        # (planner/week.py `_taken`); assuming one at this depth would
        # subtract a confident wrong number. Telling the caller is better.
        raise ValueError("%s is held in %s, not %s" % (held["ingredient"], held["unit"], unit))
    left = (held["quantity"] or 0) - amount(quantity)
    return _update(cx, held["id"], quantity=max(left, decimal.Decimal(0)))


def empty(cx, ingredient: str) -> Row | None:
    """Say a thing is gone. Only a person can say it.

    This is the 'finished' and 'discarded' end of the ledger: the shelf is
    empty, whatever the arithmetic thinks. A staple reaches 'out' here and
    nowhere else.
    """
    held = find(cx, ingredient)
    if held is None:
        return None
    if held["grade"] == STAPLE:
        return _update(cx, held["id"], level="out")
    return _update(cx, held["id"], quantity=0)


def correct(cx, ingredient: str, *, quantity: Quantity = None, unit: str | None = None,
            level: str | None = None, grade: str | None = None) -> Row | None:
    """Overrule the arithmetic with what is actually on the shelf.

    A correction is the person winning, so it sets rather than adjusts, and a
    grade change is one of the things a person may be right about: a thing
    the house once weighed and now keeps as a staple is the same row under a
    different grade, which is the point of the grade being a column.

    Returns None when nothing is held under that name; the caller writes it
    down instead, since a correction about an unrecorded thing is a thing
    being recorded.
    """
    held = find(cx, ingredient)
    if held is None:
        return None
    if level is not None:
        one_of(level, LEVELS, "level")
    if grade is not None:
        one_of(grade, GRADES, "grade")
    fields = {name: value for name, value in
              (("quantity", amount(quantity)), ("unit", unit), ("level", level),
               ("grade", grade)) if value is not None}
    if fields.get("grade") == STAPLE and level is None and held["level"] is None:
        # A thing becoming a staple is in stock. A staple's whole state is its
        # level, and a row without one is a row `in_stock` does not return.
        fields["level"] = "in_stock"
    return _update(cx, held["id"], **fields) if fields else held
