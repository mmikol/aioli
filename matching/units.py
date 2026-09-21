"""The units a recipe spells one way and the cupboard spells another.

A recipe says "2 cups", the cupboard says "400 g", and nothing can be
subtracted until the two are the same kind of number. This module is that
arithmetic and nothing else: it holds no database and no household
knowledge, so everything in it is a definition that can be checked in a
test. What is not a definition - what a cup of a particular thing weighs -
is handed in, because it is a fact about an ingredient rather than about a
unit, and it lives in `unit_conversion`.
"""
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

MASS = "mass"
VOLUME = "volume"
COUNT = "count"

# Each unit's dimension and what one of it is worth in that dimension's base
# unit - g for mass, ml for volume. A count unit has no factor at all: an egg
# and a clove are both counted and neither is worth any number of the other.
_BASE: dict[str, tuple[str, float | None]] = {
    "mg": (MASS, 0.001),
    "g": (MASS, 1.0),
    "kg": (MASS, 1000.0),
    "oz": (MASS, 28.349523125),
    "lb": (MASS, 453.59237),
    "ml": (VOLUME, 1.0),
    "cl": (VOLUME, 10.0),
    "dl": (VOLUME, 100.0),
    "l": (VOLUME, 1000.0),
    "tsp": (VOLUME, 4.92892159375),
    "tbsp": (VOLUME, 14.78676478125),
    "floz": (VOLUME, 29.5735295625),
    "cup": (VOLUME, 236.5882365),
    "pt": (VOLUME, 473.176473),
    "qt": (VOLUME, 946.352946),
    "gal": (VOLUME, 3785.411784),
    "piece": (COUNT, None),
    "clove": (COUNT, None),
    "slice": (COUNT, None),
    "can": (COUNT, None),
    "jar": (COUNT, None),
    "package": (COUNT, None),
    "bunch": (COUNT, None),
    "head": (COUNT, None),
    "stalk": (COUNT, None),
    "sprig": (COUNT, None),
    "leaf": (COUNT, None),
    "stick": (COUNT, None),
    "fillet": (COUNT, None),
    "handful": (COUNT, None),
    "pinch": (COUNT, None),
    "dash": (COUNT, None),
    "drop": (COUNT, None),
    "serving": (COUNT, None),
}

# The spellings a recipe API actually sends, against the one this house uses.
# It is a table rather than a clever rule because the spellings are a closed
# set that somebody else chose, and a rule would be wrong about "c".
_SPELLINGS: dict[str, tuple[str, ...]] = {
    "mg": ("mg", "milligram", "milligrams"),
    "g": ("g", "gr", "gm", "gram", "grams", "gramme", "grammes"),
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"),
    "oz": ("oz", "ounce", "ounces"),
    "lb": ("lb", "lbs", "pound", "pounds"),
    "ml": ("ml", "mls", "milliliter", "milliliters", "millilitre", "millilitres", "cc"),
    "cl": ("cl", "centiliter", "centiliters", "centilitre", "centilitres"),
    "dl": ("dl", "deciliter", "deciliters", "decilitre", "decilitres"),
    "l": ("l", "liter", "liters", "litre", "litres"),
    "tsp": ("t", "tsp", "tsps", "teaspoon", "teaspoons"),
    "tbsp": ("tbsp", "tbsps", "tbs", "tbl", "tablespoon", "tablespoons"),
    "floz": ("floz", "fl oz", "fluid ounce", "fluid ounces"),
    "cup": ("c", "cup", "cups"),
    "pt": ("pt", "pint", "pints"),
    "qt": ("qt", "quart", "quarts"),
    "gal": ("gal", "gallon", "gallons"),
    # "2 large eggs" arrives with "large" in the unit field, so a size is
    # read as the count it stands for rather than dropped as unknown.
    "piece": ("", "piece", "pieces", "pc", "pcs", "whole", "each", "unit", "units",
              "item", "items", "small", "medium", "large"),
    "clove": ("clove", "cloves"),
    "slice": ("slice", "slices"),
    "can": ("can", "cans", "tin", "tins"),
    "jar": ("jar", "jars"),
    "package": ("package", "packages", "pkg", "packet", "packets", "pack", "packs"),
    "bunch": ("bunch", "bunches"),
    "head": ("head", "heads"),
    "stalk": ("stalk", "stalks"),
    "sprig": ("sprig", "sprigs"),
    "leaf": ("leaf", "leaves"),
    "stick": ("stick", "sticks"),
    "fillet": ("fillet", "fillets", "filet", "filets"),
    "handful": ("handful", "handfuls"),
    "pinch": ("pinch", "pinches"),
    "dash": ("dash", "dashes"),
    "drop": ("drop", "drops"),
    "serving": ("serving", "servings", "portion", "portions"),
}

_CANONICAL: dict[str, str] = {
    spelling: canonical
    for canonical, spellings in _SPELLINGS.items()
    for spelling in spellings
}

_SEPARATORS = re.compile(r"[.,]")
_AMOUNT = re.compile(r"\s*(\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?))?")
_RANGE = re.compile(r"^\s*\d+(?:\.\d+)?(?:\s*-\s*|\s+to\s+)(\d+(?:\.\d+)?)\b")


@dataclass(frozen=True)
class Conversion:
    """One factor the household or an ingredient supplies, not physics.

    `ingredient` is None for a conversion true of anything. It mirrors a row
    of `unit_conversion`, so the board can hand these straight over.
    """
    from_unit: str
    to_unit: str
    factor: float
    ingredient: str | None = None
    source: str = "user"


@dataclass(frozen=True)
class Converted:
    """An answer, or a refusal that says what it would need.

    It is one type rather than a value-or-exception because a refusal is an
    ordinary outcome here: it becomes a question on the board.
    """
    ok: bool
    quantity: float | None
    unit: str | None
    reason: str = ""
    basis: str = ""

    def __bool__(self) -> bool:
        return self.ok


def normalise_unit(word: str | None) -> str | None:
    """The canonical spelling of a unit, or None when it is not a unit.

    An absent unit is a count, because a recipe that says "2 eggs" gives no
    unit for the reason that the egg is the unit.
    """
    if word is None:
        return "piece"
    text = " ".join(_SEPARATORS.sub(" ", str(word)).lower().split())
    if text in _CANONICAL:
        return _CANONICAL[text]
    # A plural the table does not happen to list, rather than a new unit.
    if text.endswith("s") and text[:-1] in _CANONICAL:
        return _CANONICAL[text[:-1]]
    return None


def dimension_of(unit: str | None) -> str | None:
    """Mass, volume or count - what kind of number a unit measures."""
    canonical = normalise_unit(unit)
    if canonical is None:
        return None
    return _BASE[canonical][0]


def parse_quantity(text: object) -> float | None:
    """The amount a phrase opens with, or None when it opens with a word.

    "1 1/2" is 1.5 and a vulgar fraction counts as its value, because both
    arrive from recipe text as often as a plain number does.
    """
    if text is None:
        return None
    if isinstance(text, int | float):
        return float(text)
    # Read a vulgar fraction through unicodedata rather than writing one in a
    # table here, which keeps this file ASCII as the house style asks.
    expanded = []
    for character in str(text):
        value = unicodedata.numeric(character, None)
        if value is not None and not character.isdigit():
            expanded.append(" %s " % value)
        else:
            expanded.append(character)
    phrase = "".join(expanded).strip()
    # A range is read at its top - "2-3 cloves" is 3 - because buying short
    # fails in the kitchen and buying long fails in the bin, and only one of
    # those ruins a dinner.
    spread = _RANGE.match(phrase)
    if spread:
        return float(spread.group(1))
    total: float | None = None
    position = 0
    while True:
        found = _AMOUNT.match(phrase, position)
        if found is None or found.end() == position:
            break
        amount = float(found.group(1))
        if found.group(2):
            divisor = float(found.group(2))
            if divisor == 0:
                break
            amount = amount / divisor
        total = amount if total is None else total + amount
        position = found.end()
    return total


def _generic_factor(source: str, target: str) -> float | None:
    """How many `target` one `source` is worth on definitions alone."""
    if source == target:
        return 1.0
    source_dimension, source_factor = _BASE.get(source, (None, None))
    target_dimension, target_factor = _BASE.get(target, (None, None))
    if source_dimension is None or source_dimension != target_dimension:
        return None
    if source_factor is None or target_factor is None:
        return None
    return source_factor / target_factor


def _bridge(source: str, target: str, ingredient: str | None,
            conversions: Iterable[Conversion]) -> tuple[float, str] | None:
    """A factor from the rows handed in, most specific first.

    A row is used in either direction, and its own units need not be the ones
    asked about: a density filed as "1 cup flour is 120 g" answers a question
    about millilitres, since both ends convert on definitions from there.
    """
    rows = list(conversions)
    wanted = (ingredient or "").strip().lower()
    specific = [c for c in rows if c.ingredient and c.ingredient.strip().lower() == wanted]
    general = [c for c in rows if not c.ingredient]
    for candidates, basis in ((specific, "ingredient"), (general, "table")):
        for row in candidates:
            left = normalise_unit(row.from_unit)
            right = normalise_unit(row.to_unit)
            if left is None or right is None or row.factor <= 0:
                continue
            forward_in = _generic_factor(left, source)
            forward_out = _generic_factor(right, target)
            if forward_in and forward_out:
                return row.factor * forward_out / forward_in, basis
            reverse_in = _generic_factor(right, source)
            reverse_out = _generic_factor(left, target)
            if reverse_in and reverse_out:
                return reverse_out / (row.factor * reverse_in), basis
    return None


def convert(quantity: float | None, from_unit: str | None, to_unit: str | None, *,
            ingredient: str | None = None,
            conversions: Iterable[Conversion] = ()) -> Converted:
    """`quantity` of `from_unit` expressed in `to_unit`, or a refusal.

    Definitions are used where they reach - grams to ounces, cups to
    millilitres - and a handed-in conversion where they do not, preferring
    one filed against this ingredient over one filed against everything.
    """
    source = normalise_unit(from_unit)
    target = normalise_unit(to_unit)
    if source is None:
        return Converted(False, None, None, "%r is not a unit this knows" % from_unit)
    if target is None:
        return Converted(False, None, None, "%r is not a unit this knows" % to_unit)
    if quantity is None:
        return Converted(False, None, target, "there is no amount to convert")
    factor = _generic_factor(source, target)
    basis = "same" if source == target else "generic"
    if factor is None:
        # A volume becomes a mass only through a density, and a density is a
        # fact about the ingredient: a cup of flour is about 120 g, a cup of
        # water 237 g, a cup of honey 340 g. Guessing one of those puts a
        # wrong number into a subtraction nothing downstream can question -
        # the pantry silently runs out, or silently never does, and the week
        # is planned against a kitchen that does not exist. A refusal is
        # visible: it becomes a question on the board, and a question that
        # gets answered once is a row in `unit_conversion` for good.
        found = _bridge(source, target, ingredient, conversions)
        if found is None:
            named = ingredient or "this ingredient"
            return Converted(
                False, None, target,
                "%s to %s needs what %s weighs; nothing says" % (source, target, named))
        factor, basis = found
    return Converted(True, quantity * factor, target, "", basis)
