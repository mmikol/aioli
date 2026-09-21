"""The join: a recipe's wording against the household's own names.

"2 cups diced tomatoes" has to meet "tomatoes, tinned" in the cupboard
before anything can be subtracted, and it is fuzzy in two ways - the wording
differs and the unit differs. The unit is `matching.units`; the wording is
here. Nothing in this module reads the database: the rows are handed in, so
every decision it makes can be tested without one, and so the board, the
planner and the grocery list all get the same answer.

The one rule that shapes everything below: it will be wrong often enough
that a silent wrong answer is worse than an asked question. So a match
carries a confidence and its runners-up, a low one is never subtracted from
the pantry, and the only match that is trusted outright is one a person
confirmed.

Both sides of this join are ingredients, which is all a pantry needs. A
product - a brand, a pack size, a shelf label - arrives later by hanging
underneath the ingredient it satisfies: the pantry keeps saying "tomatoes,
tinned", a product row points at that ingredient, and `resolve` and `cover`
never learn that products exist.
"""
import difflib
import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from matching.units import Conversion, Converted, convert, normalise_unit, parse_quantity

# Below this a name is not a candidate; below CONFIDENT it is a question
# rather than an answer. The gap between them is deliberate: a spelling slip
# should not cost a person a tap, and a genuine ambiguity should not be
# resolved by a machine that has no way to know.
FUZZY_CUTOFF = 0.6
CONFIDENT = 0.9

# What an alias that nobody has confirmed is worth. High enough to rank
# above a fresh fuzzy guess, low enough to still be asked about.
UNCONFIRMED = 0.75

# Preparation, size and manner: words that describe what was done to an
# ingredient rather than which ingredient it is. "Dried" and "ground" are
# deliberately absent - dried oregano and dried beans are different things
# from their fresh selves, and the pantry stocks them separately. So is
# "hot", because hot sauce is not a sauce served warm.
_PREPARATION = frozenset("""
    diced chopped sliced minced grated shredded crushed cubed julienned
    halved quartered melted softened beaten whisked mashed pitted peeled
    seeded deseeded cored stemmed trimmed drained rinsed washed thawed
    divided packed heaping heaped level optional plus taste needed garnish
    serving serve topping finely coarsely roughly thinly thickly freshly
    lightly firmly well fresh ripe organic raw cooked uncooked boneless
    skinless lean extra virgin room temperature warm cold approximately
    about good quality
""".split())

# Words that only ever glue a phrase together.
_FILLER = frozenset("a an the of and or for to into with without".split())

# Plurals the simple rules get wrong in both directions.
_IRREGULAR = {
    "leaves": "leaf",
    "loaves": "loaf",
    "halves": "half",
    "knives": "knife",
    "calves": "calf",
}
_ALREADY_SINGULAR = frozenset("""
    asparagus hummus couscous molasses watercress cress grass bass swiss
    greens oats grits chives capers sprouts noodles
""".split())

_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")
_PARENTHETICAL = re.compile(r"\([^)]*\)")


@dataclass(frozen=True)
class Alias:
    """One household mapping: this wording, digested, means this ingredient.

    A row of `ingredient_alias`. The wording itself is not carried, here or
    in the table, because it is the service's text (docs/db.md); the digest
    answers the only question a join asks - whether this has been seen before.
    """
    wording_key: str
    ingredient: str
    confirmed: bool = False


@dataclass(frozen=True)
class Match:
    """Which household ingredient a wording means, and how sure that is."""
    ingredient: str | None
    confidence: float
    source: str
    candidates: tuple[tuple[str, float], ...] = ()

    @property
    def settled(self) -> bool:
        """True when this may be acted on without asking anybody."""
        return self.ingredient is not None and self.confidence >= CONFIDENT

    @property
    def needs_confirmation(self) -> bool:
        """True when a person has to answer before this is subtracted."""
        return not self.settled


@dataclass(frozen=True)
class RecipeIngredient:
    """One line of a recipe's list, as the service words it.

    It passes through and is never written down. `quantity` and `unit` are
    whatever the service sent, including nothing at all.
    """
    wording: str
    quantity: float | str | None = None
    unit: str | None = None


# The pantry's two grades and a staple's three levels, spelled here as well.
# Not imported from kitchen/pantry.py: this module reads no database and takes
# its rows from whoever holds one, and importing the kitchen to name two
# strings would cost it that. tests/matching asserts the two spellings are
# equal, so a rename on either side fails loudly rather than quietly.
PERISHABLE = "perishable"
STAPLE = "staple"
GRADES = (PERISHABLE, STAPLE)
IN_STOCK, LOW, OUT = "in_stock", "low", "out"
LEVELS = (IN_STOCK, LOW, OUT)


@dataclass(frozen=True)
class PantryItem:
    """One row of the pantry, in the household's own words.

    A perishable carries a quantity and a unit; a staple carries a level and
    nothing more, because nobody weighs their rice.

    `grade` is one of GRADES and `level` one of LEVELS above, which are
    kitchen/pantry.py's own vocabularies.
    """
    ingredient: str
    quantity: float | None = None
    unit: str | None = None
    grade: str = PERISHABLE
    level: str | None = None


@dataclass(frozen=True)
class Need:
    """One recipe line, decided: what it means, what is held, what is short.

    `quantity` and `short` are in `unit`, which is the recipe's unit rather
    than the pantry's, because the recipe is what has to be satisfied.
    """
    wording: str
    match: Match
    quantity: float | None = None
    unit: str | None = None
    have: float | None = None
    short: float | None = None
    reason: str = ""

    @property
    def ingredient(self) -> str | None:
        return self.match.ingredient


@dataclass(frozen=True)
class Coverage:
    """What a recipe finds in the pantry, what it does not, and what it asks.

    Three lists rather than two, because "buy it" and "somebody has to say
    what this is" are different answers. A name nothing in the pantry
    resembles is missing and not a question: the house plainly does not have
    it. A name that resembles something the house does have, without anybody
    having said they are the same thing, is the question.

    The grocery list reads `missing` and puts `uncertain` on the board as
    questions; the planner scores on `covered`.
    """
    covered: tuple[Need, ...] = ()
    missing: tuple[Need, ...] = ()
    uncertain: tuple[Need, ...] = ()

    @property
    def complete(self) -> bool:
        """True when the house can cook this now without asking anything."""
        return not self.missing and not self.uncertain


def _singular(word: str) -> str:
    """One simple plural made singular. Both sides run through it, so it
    only has to be consistent, not right about English."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if len(word) <= 3 or word in _ALREADY_SINGULAR:
        return word
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "zes", "ses")):
        return word[:-2]
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def normalise_name(wording: str | None) -> str:
    """A wording reduced to the thing itself: no amount, no knifework.

    "2 cups finely diced fresh tomatoes" and "Tomatoes, diced" both land on
    "tomato". The pantry's own names go through the same function, so the
    two sides are always compared on the same terms.
    """
    if not wording:
        return ""
    text = _PARENTHETICAL.sub(" ", str(wording).lower())
    text = _PUNCTUATION.sub(" ", text)
    words = text.split()
    # An amount and its unit open the phrase; a unit word deeper in is part
    # of a name and stays - a bay leaf is not a count of leaves.
    while words:
        head = words[0]
        if head in _FILLER or head.replace(".", "").replace("/", "").isdigit():
            words.pop(0)
            continue
        if normalise_unit(head) is not None and len(words) > 1:
            words.pop(0)
            continue
        break
    kept = [w for w in words
            if w not in _PREPARATION and w not in _FILLER and not w.isdigit()]
    # A phrase that is nothing but preparation - "finely chopped" with the
    # ingredient in another field - keeps its words rather than vanishing,
    # because an empty name matches everything.
    if not kept:
        kept = words
    return " ".join(_singular(w) for w in kept)


def alias_key(wording: str) -> str:
    """The key an alias is filed under: the normalised wording, digested.

    A digest rather than the wording because the wording is the service's
    text and may not be stored (docs/db.md), and because equality is the
    only thing a stored alias is ever asked for. Fuzzy matching runs against
    the household's own names.
    """
    return hashlib.sha256(normalise_name(wording).encode("utf-8")).hexdigest()


def remember(wording: str, ingredient: str, *, confirmed: bool = True) -> Alias:
    """The alias to write when a person answers a question about a wording."""
    return Alias(alias_key(wording), ingredient, confirmed)


def alias_index(aliases: Iterable[Alias | Mapping[str, object]]) -> dict[str, Alias]:
    """Rows from `ingredient_alias`, keyed the way `resolve` looks them up."""
    index: dict[str, Alias] = {}
    for row in aliases:
        if isinstance(row, Alias):
            index[row.wording_key] = row
        else:
            index[str(row["wording_key"])] = Alias(
                str(row["wording_key"]), str(row["ingredient"]), bool(row.get("confirmed")))
    return index


def resolve(wording: str, household: Iterable[str], *,
            aliases: Mapping[str, Alias] | None = None,
            cutoff: float = FUZZY_CUTOFF, limit: int = 3) -> Match:
    """Which household ingredient a recipe's wording means.

    `household` is the names the house uses - the pantry's own column.
    `aliases` is what has already been answered, keyed by `alias_key`.

    A confirmed alias and an exact name are certain; anything else comes
    back with a confidence under CONFIDENT and its candidates - the board's
    cue to ask, not the planner's cue to subtract.

    An alias is only an answer while the house still holds what it names. A
    row survives the ingredient it points at - a name corrected on the board,
    a thing the household stopped buying - and the answer was still handed
    back as certain, which put `cover` on a name it then subscripted the
    pantry with. So an alias nothing on the shelf answers is stepped over and
    the wording is matched on its own merits.
    """
    name = normalise_name(wording)
    index: dict[str, str] = {}
    for own in household:
        index.setdefault(normalise_name(own), own)

    known = (aliases or {}).get(alias_key(wording))
    if known is not None and known.ingredient in index.values():
        confidence = 1.0 if known.confirmed else UNCONFIRMED
        return Match(known.ingredient, confidence, "alias", ((known.ingredient, confidence),))

    if name in index:
        return Match(index[name], 1.0, "exact", ((index[name], 1.0),))

    scored = sorted(
        ((own, difflib.SequenceMatcher(None, name, normalised).ratio())
         for normalised, own in index.items()),
        key=lambda pair: (-pair[1], pair[0]))
    candidates = tuple(scored[:limit])
    if candidates and candidates[0][1] >= cutoff:
        best, score = candidates[0]
        return Match(best, score, "fuzzy", candidates)
    # The near misses ride along even when none of them qualifies: a
    # question reads better with three names under it than with none.
    return Match(None, 0.0, "none", candidates)


def cover(needs: Iterable[RecipeIngredient], pantry: Iterable[PantryItem], *,
          aliases: Mapping[str, Alias] | None = None,
          conversions: Sequence[Conversion] = (),
          cutoff: float = FUZZY_CUTOFF) -> Coverage:
    """What a recipe's list finds in the pantry, in the recipe's own units.

    needs       - the recipe's lines, as the service words them. Transient:
                  nothing here is written down (docs/db.md).
    pantry      - the household's rows, perishables and staples together.
    aliases     - `ingredient_alias`, keyed by `alias_key`.
    conversions - `unit_conversion` rows, ingredient-specific and general.

    Every line comes back in exactly one of Coverage's three lists with a
    reason in plain words, so the grocery list, the planner and the board all
    read the same answer and none of them redoes the matching. A line reaches
    `covered` or `missing` only where nothing had to be assumed: an uncertain
    match and an impossible conversion are questions, because either one
    subtracted quietly is a pantry that describes a kitchen nobody has.
    """
    held: dict[str, list[PantryItem]] = {}
    for item in pantry:
        held.setdefault(item.ingredient, []).append(item)

    covered: list[Need] = []
    missing: list[Need] = []
    uncertain: list[Need] = []

    for need in needs:
        wanted = parse_quantity(need.quantity)
        unit = normalise_unit(need.unit)
        match = resolve(need.wording, held.keys(), aliases=aliases, cutoff=cutoff)

        if match.ingredient is None:
            # Nothing in the cupboard is even close, so this is a thing to
            # buy rather than a thing to ask about. Answering it as a
            # question would make an empty pantry a page of questions.
            missing.append(Need(need.wording, match, wanted, unit, have=0.0, short=wanted,
                                reason="nothing in the pantry looks like this"))
            continue
        if match.needs_confirmation:
            uncertain.append(Need(
                need.wording, match, wanted, unit,
                reason="this looks like %s, but nobody has said so" % match.ingredient))
            continue

        rows = held[match.ingredient]
        staples = [row for row in rows if row.grade == STAPLE]
        if staples:
            # A staple has no quantity to subtract, by design: the question
            # a staple answers is whether to buy more, not how much is left.
            level = staples[0].level or IN_STOCK
            line = Need(need.wording, match, wanted, unit, reason="a staple, %s" % level)
            (missing if level == OUT else covered).append(line)
            continue

        if unit is None:
            uncertain.append(Need(need.wording, match, wanted, None,
                                  reason="%r is not a unit this knows" % need.unit))
            continue
        if wanted is None:
            # No amount to subtract, so presence is the whole answer. Saying
            # so is better than inventing a number to compare against.
            covered.append(Need(need.wording, match, None, unit,
                                reason="the recipe gives no amount, so presence is all there is"))
            continue

        total = 0.0
        refusal: Converted | None = None
        for row in rows:
            moved = convert(row.quantity, row.unit, unit,
                            ingredient=match.ingredient, conversions=conversions)
            if not moved:
                refusal = moved
                break
            total += moved.quantity
        if refusal is not None:
            uncertain.append(Need(need.wording, match, wanted, unit, reason=refusal.reason))
            continue

        if total + 1e-9 >= wanted:
            covered.append(Need(need.wording, match, wanted, unit, have=total, short=0.0,
                                reason="the pantry holds enough"))
        else:
            short = wanted - total
            missing.append(Need(need.wording, match, wanted, unit, have=total, short=short,
                                reason="the pantry holds %.4g %s of %.4g" % (total, unit, wanted)))

    return Coverage(tuple(covered), tuple(missing), tuple(uncertain))
