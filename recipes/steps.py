"""The method at the stove: fetched when it is wanted, held for the hour, kept nowhere.

The board shows a plan, and a plan is the household's own. The method is not.
The terms forbid storing anything the service authored, so the steps cannot
sit in a table waiting for Tuesday evening - they are fetched at the moment
somebody opens a meal to cook it, shown, and dropped (docs/db.md).

What the terms do allow is an hour, and an hour is what a person at a stove
happens to want: the page is reloaded, a phone locks and is woken, and none
of that should spend a point or wait on the network. So this module is one
call to `information` with a small hold in front of it. The hold is memory and
nothing else - no table, no file, no log line - and the hour it keeps is
recipes/hold.py's, swept on a clock so that a quiet process is held to it too.

A point spent here is a point the ledger has to hear about. The board holds
one stove for the life of the process and a connection lives for one request,
so the recorder is handed in per fetch rather than built into the client:
a method fetched at the pan that nothing counted is a planning run told it has
a day's quota it has already spent (recipes/client.py).

Failing here costs more trust than failing anywhere else, and that is the
reason this module has the shape it does. Every other failure in this system
happens to a machine on a Saturday morning: a plan is late, somebody notices
on Monday. This one happens to a person standing in a kitchen with the pan
already hot. So there is no exception to catch and no blank card. A method that
did not land comes back with `ok` false, one word saying what went wrong and a
sentence in plain words for the board to print.
"""
import html
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from matching.ingredients import RecipeIngredient
from recipes.client import (
    NO_KEY,
    QUOTA,
    REFUSED,
    Spoonacular,
    SpoonacularError,
    trouble_of,
)
from recipes.hold import HELD_AT_MOST, HOLD_SECONDS, SWEEP_SECONDS, Hold

# The hour, the count and the sweep are recipes/hold.py's, named here as well
# because they are what a caller of this module asks about. The ceiling is the
# terms' rule and a hold refuses more than an hour whatever it is handed.

# The fifth word a caller may find on a Method, and the one that comes with
# `ok` true: the other four are recipes/client.py's, imported above.
NO_STEPS = "no steps"

_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"</li\s*>|</p\s*>|<br\s*/?>|\n", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Step:
    """One instruction, numbered the way the person at the stove counts.

    `part` is the heading the service groups a run of steps under - the
    sauce, the finish - and is empty where there is only one list. It is
    carried because dropping it runs two sub-recipes together into what reads
    as one pan.
    """
    number: int
    text: str
    part: str = ""
    equipment: tuple[str, ...] = ()


@dataclass(frozen=True)
class Method:
    """What the stove needs, or what to say instead of it.

    One type rather than a value-or-exception, for the reason
    `matching.units.Converted` is one: a service that cannot be reached is an
    ordinary outcome here, and the board renders it instead of handling it.
    `ok` says the fetch landed. `trouble` is the one word a caller branches
    on - quota, unreachable, refused, no key, no steps - and `sentence` is
    the plain words a person reads in place of the card.

    One case sets both `ok` and `trouble`: a fetch that landed with nothing
    to cook from, 'no steps'. The ingredients are there and a caller
    subtracting stock wants them, so it is not a failure; a caller about to
    show a method reads `trouble` and prints the sentence in place of an
    empty card. Every other trouble comes with `ok` false.

    `lines` are `matching.ingredients.RecipeIngredient`, the type `cover`
    takes, so a board that wants to say what the cupboard is short of passes
    them straight on without reshaping anything.

    Frozen, and made of tuples, so a caller handed a held method cannot edit
    what the next reload will see. Nothing in it is written down: it is the
    service's text, and it lives in this process for at most an hour
    (docs/db.md).
    """
    recipe_id: int
    ok: bool = False
    title: str = ""
    ready_minutes: int | None = None
    servings: int | None = None
    steps: tuple[Step, ...] = ()
    lines: tuple[RecipeIngredient, ...] = ()
    equipment: tuple[str, ...] = ()
    trouble: str = ""
    sentence: str = ""

    def __bool__(self) -> bool:
        return self.ok


class Stove:
    """One call to `information`, with an hour's memory in front of it.

    The board keeps one for the life of the process, because a hold is only
    worth having if the next request finds it.

    `client` is a `recipes.client.Spoonacular`, the name every other module
    here calls it by. Left out, one is built from the environment at the first
    fetch rather than at construction, so a board with no key still starts and
    still shows the week - only the steps are missing.

    `clock` returns seconds and has to be monotonic; it is the hold's, and
    tests hand in their own so the hour is tested by moving it rather than by
    waiting one out.
    """

    def __init__(self, client: Spoonacular | None = None, *,
                 clock: Callable[[], float] = time.monotonic, hold_seconds: float = HOLD_SECONDS,
                 hold_at_most: int = HELD_AT_MOST, sweep_every: float = SWEEP_SECONDS):
        self._client = client
        self._kept = Hold(clock=clock, hold_seconds=hold_seconds,
                          hold_at_most=hold_at_most, sweep_every=sweep_every)
        self._lock = threading.Lock()
        self._spending = None

    def method(self, recipe_id: int, *, usage: Callable | None = None) -> Method:
        """What is at the stove for this recipe: the hold if it is fresh, the service if not.

        `usage` is the ledger's recorder for this request, as
        `recipes.client.usage_into` makes one from a connection. It is bound
        for the length of the fetch and let go again, because a stove lives
        for the process and a connection lives for one request. A held method
        spends nothing, so nothing is recorded for it.

        The lock spans the fetch on purpose. The board is threaded, so two
        tabs opening the same meal would otherwise spend two points for one
        answer and a point is a real cost; a household of one can wait behind
        the first of them.
        """
        key = int(recipe_id)
        with self._lock:
            found = self._kept.get(key)
            if found is not None:
                return found
            self._spending = usage
            try:
                answer = self._fetch(key)
            finally:
                self._spending = None
            if answer.ok:
                self._kept.put(key, answer)
            # A failure is never held. A service down for a minute must not
            # read as an hour of blankness to somebody at the pan, and asking
            # again after a refusal costs nothing.
            return answer

    def held(self) -> int:
        """How many methods are being held, once what has expired is gone."""
        return len(self._kept)

    def forget(self, recipe_id: int | None = None) -> None:
        """Drop one held method, or all of them. The rule is recipes/hold.py
        `Hold.forget`'s."""
        self._kept.forget(None if recipe_id is None else int(recipe_id))

    def stop(self) -> None:
        """Let the hour go and drop what is held. What a process says on its way out."""
        self._kept.stop()

    def _record(self, points: float, calls: int) -> None:
        """Hand a fetch's cost to the recorder bound for it, if there is one.

        The client is built once and the ledger is written per request, so
        what a call cost is passed on rather than kept here.
        """
        if self._spending is not None:
            self._spending(points, calls)

    def _fetch(self, recipe_id: int) -> Method:
        """One call out, with every way it can fail turned into a sentence.

        The client is built at the first fetch and not before, and wired to
        `_record` so every point this stove spends reaches whichever ledger
        the request that asked for it is writing to. One handed in by a caller
        keeps the recorder that caller gave it.
        """
        try:
            if self._client is None:
                self._client = Spoonacular(usage=self._record)
            payload = self._client.information(recipe_id)
        except SpoonacularError as refused:
            return _refused(recipe_id, refused)
        return _read(recipe_id, payload)


def _refused(recipe_id: int, refusal: SpoonacularError) -> Method:
    """A call out that did not land, as the word and the sentence at the pan.

    The word is recipes/client.py's, so the stove, the planner and the list
    all agree about which failure this was. The sentence is this module's,
    because it is read by somebody standing over a hot pan and wants to say
    what that person can do next.
    """
    trouble = trouble_of(refusal)
    if trouble == NO_KEY:
        return _trouble(recipe_id, trouble,
                        "There is no recipe service key set, so the steps cannot be"
                        " fetched. The plan and the pantry are unaffected.")
    if trouble == QUOTA:
        return _trouble(recipe_id, trouble,
                        "The day's recipe quota is spent, so the steps cannot be fetched"
                        " until tomorrow.")
    if trouble == REFUSED:
        return _trouble(recipe_id, trouble,
                        "The recipe service answered %s, so the steps are not here."
                        " It is worth trying again in a minute." % refusal.status)
    return _trouble(recipe_id, trouble,
                    "The recipe service cannot be reached, so the steps are not here."
                    " It is worth trying again in a minute.")


def _read(recipe_id: int, payload: object) -> Method:
    """The payload reduced to what the stove needs, and nothing kept of the rest."""
    if not isinstance(payload, dict):
        return _trouble(recipe_id, REFUSED,
                        "The recipe service answered with something that is not a recipe.")
    steps = _steps(payload)
    method = Method(recipe_id=recipe_id, ok=True,
                    title=_text(payload.get("title")),
                    ready_minutes=whole_number(payload.get("readyInMinutes")),
                    servings=whole_number(payload.get("servings")),
                    steps=steps,
                    lines=lines_of(payload),
                    equipment=_gathered(step.equipment for step in steps))
    if not steps:
        # A recipe the service holds no method for is not a failure of the
        # service, and it is still a blank card unless somebody says so.
        return replace(method, trouble=NO_STEPS,
                       sentence="The service publishes no method for this recipe, only its"
                                " ingredients.")
    return method


def _steps(payload: dict) -> tuple[Step, ...]:
    """The instructions, from the analysed list or from the prose behind it.

    `analyzedInstructions` is the good case and is empty often enough that a
    fallback is not a nicety: a method written as one paragraph is still a
    method, and the alternative on that recipe is the blank card. The numbers
    are this module's own, because the service restarts them at one for each
    named part and a person at a stove counts straight through.
    """
    found = []
    for block in payload.get("analyzedInstructions") or ():
        if not isinstance(block, dict):
            continue
        part = _text(block.get("name"))
        for step in block.get("steps") or ():
            if not isinstance(step, dict):
                continue
            text = _text(step.get("step"))
            if text:
                found.append(Step(len(found) + 1, text, part, _names(step.get("equipment"))))
    if found:
        return tuple(found)
    return tuple(Step(number, text)
                 for number, text in enumerate(_prose(payload.get("instructions")), 1))


def _prose(raw: object) -> tuple[str, ...]:
    """A method sent as one lump of markup, split into things to read.

    The service sends `instructions` as HTML about as often as plain text, so
    the tags come out and the list items are where it breaks. It is a
    fallback and not a parser: what it cannot split it hands over whole.
    """
    if not isinstance(raw, str):
        return ()
    pieces = (_text(html.unescape(_TAG.sub(" ", piece))) for piece in _BREAK.split(raw))
    return tuple(piece for piece in pieces if piece)


def ingredient_rows(payload: object) -> tuple[dict, ...]:
    """A payload's raw ingredient rows, whichever call answered with it.

    /information answers `extendedIngredients`; a search answers
    `usedIngredients` plus `missedIngredients`, and which of those the pantry
    actually answers is this kitchen's arithmetic to do rather than the
    service's to be believed about. Which key holds them is known here and
    nowhere else, so a key the service renames is changed once.

    Raw, because one caller wants a field this house does not model: the part
    of a shop a supermarket files a thing under (planner/groceries.py). A
    caller that wants only the wordings takes `lines_of`.
    """
    if not isinstance(payload, dict):
        return ()
    found = payload.get("extendedIngredients")
    if not isinstance(found, list) or not found:
        found = (list(payload.get("usedIngredients") or [])
                 + list(payload.get("missedIngredients") or []))
    return tuple(row for row in found or () if isinstance(row, dict))


def wording_of(row: dict) -> str:
    """One ingredient row's words, as the recipe writes them.

    `original` is the line a person reads off a card, and what
    `normalise_name` strips the amount off anyway. One wording serves the
    stove and the cupboard alike.
    """
    return (_text(row.get("original")) or _text(row.get("originalName"))
            or _text(row.get("name")))


def lines_of(payload: object, *, most: int | None = None) -> tuple[RecipeIngredient, ...]:
    """A payload's ingredient list, in the shape `matching.ingredients.cover` takes.

    `most` is a ceiling for a caller that has one: `number` is a request to
    the service and a ceiling is a promise the caller made (planner/).
    """
    rows = ingredient_rows(payload)
    if most is not None:
        rows = rows[:most]
    found = []
    for row in rows:
        wording = wording_of(row)
        if wording:
            found.append(RecipeIngredient(wording, row.get("amount"),
                                          _text(row.get("unit")) or None))
    return tuple(found)


def equipment_of(payload: object) -> tuple[str, ...]:
    """What a payload says the cook needs from the kitchen, first wanted first.

    A search result names no equipment, so this is usually empty and nothing
    is dropped; the fuller payload the board already holds when it is showing
    a method is where it comes from. An equipment name is the kitchen's
    vocabulary rather than the recipe's - a skillet is the word for a skillet
    - so it feeds `kitchen.settings.missing_equipment` unchanged.
    """
    if not isinstance(payload, dict):
        return ()
    return _gathered(step.equipment for step in _steps(payload))


def _names(items: object) -> tuple[str, ...]:
    """The equipment one step calls for, in order and without repeats. Why it
    passes through unchanged is `equipment_of`'s."""
    found = []
    for item in items or ():
        name = _text(item.get("name")) if isinstance(item, dict) else _text(item)
        if name and name not in found:
            found.append(name)
    return tuple(found)


def _gathered(groups: Iterable[Iterable[str]]) -> tuple[str, ...]:
    """Every step's equipment as one list, in the order it is first wanted."""
    found = []
    for group in groups:
        for name in group:
            if name not in found:
                found.append(name)
    return tuple(found)


def _trouble(recipe_id: int, trouble: str, sentence: str) -> Method:
    """A method that did not land, carrying what to show in its place."""
    return Method(recipe_id=recipe_id, ok=False, trouble=trouble, sentence=sentence)


def _text(value: object) -> str:
    """A string off the payload, its whitespace collapsed, or nothing."""
    if not isinstance(value, str):
        return ""
    return _SPACES.sub(" ", value).strip()


def whole_number(value: object) -> int | None:
    """A count the service sends as an int, as a float, or not at all.

    Public because the planner reads the same `servings` field off the same
    payloads, and a second copy of four lines is a second place to be wrong
    about what the service sends.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(round(value))
