"""What is in the house, in two grades.

A perishable carries a quantity, a unit, the date it came in and a rough
shelf life, because that is where waste happens and where the arithmetic has
to work. A staple carries a level and nothing else: nobody weighs their
rice, and a pantry that asks them to is a pantry abandoned inside a
fortnight. The precision is spent where it is repaid (pm/backlog.md).

The grade is a column rather than two tables, so a thing can change grade
without moving. That is also why every function here takes an ingredient
and asks the row what grade it is, rather than the caller knowing.

Nothing in this module writes to `stock_move`. Moving stock without a ledger
line is how the table starts describing a kitchen that does not exist, so
the pantry is moved through kitchen/moves.py and read through here.
"""
import datetime
import decimal

PERISHABLE = "perishable"
STAPLE = "staple"
GRADES = (PERISHABLE, STAPLE)

# A staple's whole vocabulary. 'out' is a person's word: see `subtract`.
LEVELS = ("in_stock", "low", "out")

# The day a perishable turns. Postgres adds an integer to a date as days,
# which is the whole arithmetic the planner's waste term rests on.
TURNS_ON = "(acquired_on + shelf_life_days)"

FIELDS = ("ingredient", "grade", "quantity", "unit", "acquired_on", "shelf_life_days", "level")


def amount(value):
    """A quantity as an exact decimal, because every quantity column is numeric.

    A caller hands over whatever a recipe or a form gave it, and half a kilo
    arriving as a float and leaving as 0.49999 is the kind of drift that is
    never noticed and never forgiven. kitchen/moves.py writes quantities too,
    which is why this is not private to this module.
    """
    if value is None or isinstance(value, decimal.Decimal):
        return value
    return decimal.Decimal(str(value))


def add_perishable(cx, ingredient, quantity, unit, shelf_life_days, acquired_on=None):
    """Book in something that will spoil.

    The shelf life is not optional here although the column allows a null,
    because it is the whole reason a perishable is a perishable: it is what
    makes ageing stock rank ahead of fresh, and a row without it is invisible
    to the planner it was entered for.
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


def add_staple(cx, ingredient, level="in_stock"):
    """Book in something that does not spoil on a schedule."""
    if level not in LEVELS:
        raise ValueError("a level is one of %s, not %r" % (", ".join(LEVELS), level))
    return cx.execute(
        "insert into pantry (ingredient, grade, level) values (%s, 'staple', %s) returning *",
        (ingredient.strip(), level)).fetchone()


def find(cx, ingredient):
    """The row holding an ingredient, or None.

    Matched on lower(ingredient), which is what the index is on. A second lot
    of the same thing is its own row - two chickens bought a week apart turn
    a week apart - and the one nearest turning is the one handed back, so
    subtracting cooks the older stock first. That ordering is the waste rule
    in one line.
    """
    return cx.execute(
        "select * from pantry where lower(ingredient) = lower(%s)"
        " order by " + TURNS_ON + " nulls last, id limit 1", (ingredient.strip(),)).fetchone()


def holdings(cx, ingredient):
    """Every lot of an ingredient, nearest turning first."""
    return cx.execute(
        "select *, " + TURNS_ON + " as turns_on from pantry"
        " where lower(ingredient) = lower(%s) order by " + TURNS_ON + " nulls last, id",
        (ingredient.strip(),)).fetchall()


def in_stock(cx):
    """What the house actually has.

    A perishable with nothing left is a row waiting to be bought again rather
    than stock, and a staple marked out is the same. Both are kept, because a
    thing the household buys is worth remembering the shelf life of.
    """
    return cx.execute(
        "select *, " + TURNS_ON + " as turns_on from pantry"
        " where (grade = 'perishable' and coalesce(quantity, 0) > 0)"
        "    or (grade = 'staple' and level <> 'out')"
        " order by lower(ingredient)").fetchall()


def ingredient_names(cx):
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


def turning_soonest(cx, within_days=None, limit=None, today=None):
    """Perishables by the day they turn, soonest first.

    The planner ranks ageing stock ahead of fresh, and the midweek mail asks
    about what is nearly gone, and both of them are this query. A row without
    a date or a shelf life cannot be ranked, so it is not here: `days_left`
    would be a guess, and a guess is what the whole waste figure would then
    be computed from.

    Today is the household's, not the database's. `current_date` is whatever
    timezone the server happens to run in, which on this stack is UTC, so an
    evening west of Greenwich would age every perishable by a day and tell
    someone their spinach turns tomorrow when it turns the day after. The
    caller's date is the one the household keeps.
    """
    today = today or datetime.date.today()
    sql = ("select *, " + TURNS_ON + " as turns_on, " + TURNS_ON + " - %s::date as days_left"
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


def update(cx, pantry_id, **fields):
    """Correct a row by hand, which is what the board does.

    A grade change is a normal edit and not a special case, which is the
    point of the grade being a column.
    """
    unknown = [name for name in fields if name not in FIELDS]
    if unknown:
        raise ValueError("a pantry row has no %s" % ", ".join(sorted(unknown)))
    if not fields:
        return cx.execute("select * from pantry where id = %s", (pantry_id,)).fetchone()
    names = sorted(fields)
    sets = ", ".join("%s = %%s" % name for name in names) + ", updated_at = now()"
    return cx.execute("update pantry set " + sets + " where id = %s returning *",
                      [fields[name] for name in names] + [pantry_id]).fetchone()


def remove(cx, pantry_id):
    """Take a row out. True when there was one.

    The ledger survives it: `stock_move.pantry_id` is set null and the moves
    keep their ingredient, so deleting a row loses the balance and not the
    history of how it got there.
    """
    return cx.execute("delete from pantry where id = %s", (pantry_id,)).rowcount > 0


def restock(cx, ingredient, quantity=None, unit=None, shelf_life_days=None,
            acquired_on=None, grade=None):
    """Put stock in: a shop, or a correction upward.

    A staple comes back to 'in_stock'. A perishable arriving is a new row
    rather than a bigger number on the old one, because two lots bought a
    week apart turn a week apart and adding them together loses the older
    date - which is the one the planner needs. The same lot arriving twice on
    one day is the exception, and adding is right there.

    An unstated shelf life is inherited from the last lot of the same thing,
    since a household buys the same chicken repeatedly; an unstated grade is
    read off the arguments, because a quantity and a unit are what a
    perishable is.
    """
    ingredient = ingredient.strip()
    held = find(cx, ingredient)
    if grade is None:
        grade = held["grade"] if held is not None else (
            PERISHABLE if quantity is not None and unit is not None else STAPLE)
    if grade not in GRADES:
        raise ValueError("a grade is one of %s, not %r" % (", ".join(GRADES), grade))

    if grade == STAPLE:
        if held is not None and held["grade"] == STAPLE:
            return update(cx, held["id"], level="in_stock")
        return add_staple(cx, ingredient)

    acquired_on = acquired_on or datetime.date.today()
    if shelf_life_days is None and held is not None:
        shelf_life_days = held["shelf_life_days"]
    same_lot = cx.execute(
        "select * from pantry where lower(ingredient) = lower(%s) and grade = 'perishable'"
        " and acquired_on = %s and lower(coalesce(unit, '')) = lower(coalesce(%s, ''))"
        " order by id limit 1", (ingredient, acquired_on, unit)).fetchone()
    if same_lot is not None:
        return update(cx, same_lot["id"],
                      quantity=(same_lot["quantity"] or 0) + (amount(quantity) or 0))
    return add_perishable(cx, ingredient, quantity, unit, shelf_life_days, acquired_on)


def subtract(cx, ingredient, quantity=None, unit=None):
    """Take stock out, which the two grades do not do the same way.

    A perishable's quantity is arithmetic and may land on zero. A staple's
    level is a judgement, so cooking with one moves it to 'low' at most and
    never to 'out': only the person looking at the jar knows it is empty, and
    a planner that decided that for them would leave rice off the list.
    Saying a thing is gone is `empty` below, and it is a person's word.

    A perishable used without a quantity is left alone and not guessed at.
    The move is still recorded by the caller, so the drift shows in the
    ledger rather than becoming a number the waste figure is computed from.

    Returns the row as it now stands, or None when the house does not hold
    the thing at all - which is a fact worth handing back rather than
    raising, since cooking with something unrecorded is normal.
    """
    held = find(cx, ingredient)
    if held is None:
        return None
    if held["grade"] == STAPLE:
        return update(cx, held["id"], level="low" if held["level"] == "in_stock" else held["level"])
    if quantity is None:
        return held
    if unit and held["unit"] and unit.strip().lower() != held["unit"].strip().lower():
        # A recipe's words are not the pantry's words, and neither are its
        # units. The conversion belongs in the ingredient_product table that
        # item brings; assuming one here would subtract a confident wrong
        # number, which is worse than the caller being told.
        raise ValueError("%s is held in %s, not %s" % (held["ingredient"], held["unit"], unit))
    left = (held["quantity"] or 0) - amount(quantity)
    return update(cx, held["id"], quantity=max(left, decimal.Decimal(0)))


def empty(cx, ingredient):
    """Say a thing is gone, which only a person can say.

    This is the 'finished' and 'discarded' end of the ledger: the shelf is
    empty, whatever the arithmetic thinks. A staple reaches 'out' here and
    nowhere else.
    """
    held = find(cx, ingredient)
    if held is None:
        return None
    if held["grade"] == STAPLE:
        return update(cx, held["id"], level="out")
    return update(cx, held["id"], quantity=0)


def correct(cx, ingredient, quantity=None, unit=None, level=None):
    """Overrule the arithmetic with what is actually on the shelf.

    A correction is the person winning, so it sets rather than adjusts.
    Returns None when nothing is held under that name; the caller writes it
    down instead, since a correction about an unrecorded thing is a thing
    being recorded.
    """
    held = find(cx, ingredient)
    if held is None:
        return None
    if level is not None and level not in LEVELS:
        raise ValueError("a level is one of %s, not %r" % (", ".join(LEVELS), level))
    fields = {name: value for name, value in
              (("quantity", amount(quantity)), ("unit", unit), ("level", level))
              if value is not None}
    return update(cx, held["id"], **fields) if fields else held
