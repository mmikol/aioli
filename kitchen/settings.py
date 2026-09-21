"""The household's facts: what it has decided, what it will not eat, what it cooks with.

Three tables and one habit. `settings` is a key, a value and where the value
came from; `dietary_rule` is what will not be eaten; `equipment` is what the
kitchen actually has.

The habit is that nothing here assumes a person typed anything. Household
size is the household's, a budget is the accountant's and a protein floor
would be the trainer's (docs/fleet.md), and the day one of them starts
arriving from another agent is a change of `source` and not a migration.
So a reader reads the value and a writer says who said so.

Every function takes a connection from db.psql.connect, whose rows are dicts.
"""
import datetime

# What a household gets before it has said anything. These are not rows: a
# default that wrote itself into the table would be indistinguishable from a
# figure someone chose, and `origin` below is how a caller tells them apart.
#
# The days are the rhythm the backlog settles on - two shops and two cook
# sessions a week - arranged so a shop lands the day before a cook, so fresh
# things arrive near to when they are cooked.
DEFAULTS = {
    "household_size": "1",
    "max_ready_minutes_weeknight": "45",
    "max_ready_minutes_weekend": "90",
    "cook_sessions_per_week": "2",
    "shop_trips_per_week": "2",
    "cook_days": "sunday,wednesday",
    "shop_days": "saturday,tuesday",
}

# Week order, so a day list comes back in the order a week happens in rather
# than the order it was typed in.
WEEK = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

SOURCES = ("user", "default", "agent")

KINDS = ("diet", "intolerance", "dislike")


def get(cx, key, default=None):
    """The value for a key, as text. A missing row is not an error.

    The source is deliberately not consulted: a figure is worth the same
    whoever stated it, and a reader that treated an agent's value as less
    real than a person's would have to be rewritten on the day the
    accountant arrives.
    """
    row = cx.execute("select value from settings where key = %s", (key,)).fetchone()
    if row is not None:
        return row["value"]
    return DEFAULTS.get(key) if default is None else default


def origin(cx, key):
    """Who said so: 'user', 'agent', or 'default' when nobody has.

    This is the one place the source matters - the board showing where a
    figure came from, and a later agent deciding whether it may overwrite
    one a person typed.
    """
    row = cx.execute("select source from settings where key = %s", (key,)).fetchone()
    return row["source"] if row is not None else "default"


def put(cx, key, value, source="user"):
    """State a fact. `source` says who did, and it is not always a person."""
    if source not in SOURCES:
        raise ValueError("a source is one of %s, not %r" % (", ".join(SOURCES), source))
    return cx.execute(
        "insert into settings (key, value, source, updated_at)"
        " values (%s, %s, %s, now())"
        " on conflict (key) do update set value = excluded.value,"
        " source = excluded.source, updated_at = now() returning *",
        (key, str(value), source)).fetchone()


def forget(cx, key):
    """Drop a stated fact. The key goes back on its default."""
    return cx.execute("delete from settings where key = %s", (key,)).rowcount > 0


def stated(cx):
    """Every fact the household has actually stated, newest first.

    Not the same as what a reader gets: the defaults above answer for the
    keys nobody has touched, and they are absent here on purpose.
    """
    return cx.execute("select * from settings order by updated_at desc, key").fetchall()


def _number(cx, key):
    """A setting read as a whole number, blaming the key when it will not."""
    value = get(cx, key)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("setting %s is not a number: %r" % (key, value)) from None


def household_size(cx):
    """How many a meal cooks for. One, until someone says otherwise."""
    return _number(cx, "household_size")


def max_ready_minutes_weeknight(cx):
    """How long a cook may take on a working evening."""
    return _number(cx, "max_ready_minutes_weeknight")


def max_ready_minutes_weekend(cx):
    """How long a cook may take when the afternoon is free."""
    return _number(cx, "max_ready_minutes_weekend")


def max_ready_minutes(cx, day):
    """The cap for a given date: the number the search filters on.

    A Saturday afternoon and a Tuesday evening are not the same amount of
    time, and a single cap set for both is wrong twice.
    """
    if isinstance(day, datetime.datetime):
        day = day.date()
    if day.weekday() >= 5:
        return max_ready_minutes_weekend(cx)
    return max_ready_minutes_weeknight(cx)


def cook_sessions_per_week(cx):
    """How many times the week's cooking is grouped into."""
    return _number(cx, "cook_sessions_per_week")


def shop_trips_per_week(cx):
    """How many times the week's buying is grouped into."""
    return _number(cx, "shop_trips_per_week")


def days(value):
    """A comma-separated day list, lowercased, deduplicated and in week order.

    An unknown day is raised rather than dropped: a typo that silently
    removes a cook session is a week planned around a session nobody
    scheduled, and it would be found a fortnight later.
    """
    named = []
    for word in str(value).split(","):
        word = word.strip().lower()
        if not word:
            continue
        if word not in WEEK:
            raise ValueError("%r is not a day of the week" % word)
        if word not in named:
            named.append(word)
    return [day for day in WEEK if day in named]


def cook_days(cx):
    """The days the household cooks on, in week order."""
    return days(get(cx, "cook_days"))


def shop_days(cx):
    """The days the household shops on, in week order."""
    return days(get(cx, "shop_days"))


def dietary_rules(cx, kind=None):
    """What will not be eaten, all of it or one kind of it."""
    if kind is None:
        return cx.execute("select * from dietary_rule order by kind, value").fetchall()
    if kind not in KINDS:
        raise ValueError("a dietary rule is one of %s, not %r" % (", ".join(KINDS), kind))
    return cx.execute("select * from dietary_rule where kind = %s order by value",
                      (kind,)).fetchall()


def add_dietary_rule(cx, kind, value, note=None):
    """Record something that will not be eaten.

    Stating the same rule twice updates its note rather than failing: the
    board re-sending a row is not an error, it is someone pressing save.
    """
    if kind not in KINDS:
        raise ValueError("a dietary rule is one of %s, not %r" % (", ".join(KINDS), kind))
    return cx.execute(
        "insert into dietary_rule (kind, value, note) values (%s, %s, %s)"
        " on conflict (kind, value) do update set note = excluded.note returning *",
        (kind, value.strip().lower(), note)).fetchone()


def remove_dietary_rule(cx, kind, value):
    """Lift a rule. True when there was one to lift."""
    return cx.execute("delete from dietary_rule where kind = %s and lower(value) = lower(%s)",
                      (kind, value.strip())).rowcount > 0


def recipe_filters(cx):
    """What will not be eaten, shaped for the search the planner already makes.

    Spoonacular's complexSearch takes `diet`, `intolerances` and
    `excludeIngredients` on the same call, so these are three query parameters
    and not a filter run over the results: a recipe that was never going to be
    cooked should not cost a point to find out about.

    The diet is one string because the API takes one, and it is None rather
    than empty so a caller drops the parameter instead of sending a blank.
    """
    diets, intolerances, disliked = [], [], []
    for row in dietary_rules(cx):
        {"diet": diets, "intolerance": intolerances, "dislike": disliked}[row["kind"]].append(
            row["value"])
    return {
        "diet": ",".join(diets) or None,
        "intolerances": intolerances,
        "exclude_ingredients": disliked,
    }


def equipment(cx):
    """Everything the kitchen has been asked about, present or not."""
    return cx.execute("select * from equipment order by name").fetchall()


def add_equipment(cx, name, present=True):
    """Write down a piece of kit, or say it has left the kitchen."""
    return cx.execute(
        "insert into equipment (name, present) values (%s, %s)"
        " on conflict (name) do update set present = excluded.present returning *",
        (name.strip().lower(), present)).fetchone()


def remove_equipment(cx, name):
    """Take a piece of kit off the list entirely. True when it was on it.

    Different from setting it absent: a row saying `present = false` is the
    household stating it does not own the thing, and the filter below reads
    it. Removing the row says nothing either way.
    """
    return cx.execute("delete from equipment where name = lower(%s)",
                      (name.strip(),)).rowcount > 0


def has_equipment(cx, name):
    """Whether a recipe asking for this can be cooked here.

    Unknown means available. The table starts empty and fills as recipes ask
    for things, so the other rule - unlisted means missing - would drop every
    suggestion on the first day and keep doing it until someone had typed out
    their whole kitchen. Only a row that says `present = false` drops a
    recipe.
    """
    row = cx.execute("select present from equipment where name = lower(%s)",
                     (name.strip(),)).fetchone()
    return True if row is None else row["present"]


def missing_equipment(cx, required):
    """Which of a recipe's equipment this kitchen does not have, in order.

    Empty means the recipe is cookable here; anything in it is the reason to
    drop the recipe, and worth showing rather than filtering silently.
    """
    return [name for name in required if not has_equipment(cx, name)]
