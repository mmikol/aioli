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
from dataclasses import dataclass, replace

from matching.ingredients import RecipeIngredient
from recipes.client import MissingKey, QuotaExhausted, Spoonacular, SpoonacularError
from recipes.hold import HELD_AT_MOST, HOLD_SECONDS, SWEEP_SECONDS, Hold

# The hour, the count and the sweep are recipes/hold.py's, named here as well
# because they are what a caller of this module asks about. The ceiling is the
# terms' rule and a hold refuses more than an hour whatever it is handed.

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

    `chef` is a `recipes.client.Spoonacular`. Left out, one is built from the
    environment at the first fetch rather than at construction, so a board
    with no key still starts and still shows the week - only the steps are
    missing.

    `clock` returns seconds and has to be monotonic; it is the hold's, and
    tests hand in their own so the hour is tested by moving it rather than by
    waiting one out.
    """

    def __init__(self, chef=None, *, clock=time.monotonic, hold_seconds=HOLD_SECONDS,
                 hold_at_most=HELD_AT_MOST, sweep_every=SWEEP_SECONDS):
        self._chef = chef
        self._kept = Hold(clock=clock, hold_seconds=hold_seconds,
                          hold_at_most=hold_at_most, sweep_every=sweep_every)
        self._lock = threading.Lock()
        self._spending = None

    def method(self, recipe_id, usage=None) -> Method:
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

    def forget(self, recipe_id=None) -> None:
        """Drop one held method, or all of them.

        The terms say everything obtained goes when the key does, so saying
        it has to be one call and not a walk over a dict nobody else can see.
        """
        self._kept.forget(None if recipe_id is None else int(recipe_id))

    def stop(self) -> None:
        """Let the hour go and drop what is held. What a process says on its way out."""
        self._kept.stop()

    def _record(self, points, calls) -> None:
        """Hand a fetch's cost to the recorder bound for it, if there is one.

        The client is built once and the ledger is written per request, so
        what a call cost is passed on rather than kept here.
        """
        if self._spending is not None:
            self._spending(points, calls)

    def _fetch(self, recipe_id) -> Method:
        """One call out, with every way it can fail turned into a sentence."""
        try:
            chef = self._client()
        except MissingKey:
            return _trouble(recipe_id, "no key",
                            "There is no recipe service key set, so the steps cannot be"
                            " fetched. The plan and the pantry are unaffected.")
        try:
            payload = chef.information(recipe_id)
        except QuotaExhausted:
            return _trouble(recipe_id, "quota",
                            "The day's recipe quota is spent, so the steps cannot be fetched"
                            " until tomorrow.")
        except SpoonacularError as refused:
            if refused.status is None:
                return _trouble(recipe_id, "unreachable",
                                "The recipe service cannot be reached, so the steps are not"
                                " here. It is worth trying again in a minute.")
            return _trouble(recipe_id, "refused",
                            "The recipe service answered %s, so the steps are not here."
                            " It is worth trying again in a minute." % refused.status)
        return _read(recipe_id, payload)

    def _client(self):
        """The client, built at the first fetch and not before.

        Wired to `_record`, so every point this stove spends reaches whichever
        ledger the request that asked for it is writing to. A client handed in
        by a caller keeps the recorder that caller gave it.
        """
        if self._chef is None:
            self._chef = Spoonacular(usage=self._record)
        return self._chef


def _read(recipe_id, payload) -> Method:
    """The payload reduced to what the stove needs, and nothing kept of the rest."""
    if not isinstance(payload, dict):
        return _trouble(recipe_id, "refused",
                        "The recipe service answered with something that is not a recipe.")
    steps = _steps(payload)
    method = Method(recipe_id=recipe_id, ok=True,
                    title=_text(payload.get("title")),
                    ready_minutes=_whole(payload.get("readyInMinutes")),
                    servings=_whole(payload.get("servings")),
                    steps=steps,
                    lines=_lines(payload),
                    equipment=_gathered(step.equipment for step in steps))
    if not steps:
        # A recipe the service holds no method for is not a failure of the
        # service, and it is still a blank card unless somebody says so.
        return replace(method, trouble="no steps",
                       sentence="The service publishes no method for this recipe, only its"
                                " ingredients.")
    return method


def _steps(payload) -> tuple[Step, ...]:
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


def _prose(raw) -> tuple[str, ...]:
    """A method sent as one lump of markup, split into things to read.

    The service sends `instructions` as HTML about as often as plain text, so
    the tags come out and the list items are where it breaks. It is a
    fallback and not a parser: what it cannot split it hands over whole.
    """
    if not isinstance(raw, str):
        return ()
    pieces = (_text(html.unescape(_TAG.sub(" ", piece))) for piece in _BREAK.split(raw))
    return tuple(piece for piece in pieces if piece)


def _lines(payload) -> tuple[RecipeIngredient, ...]:
    """The ingredient list, in the shape `matching.ingredients.cover` takes.

    `original` is the line as the recipe writes it: what a person reads off a
    card, and what `normalise_name` strips the amount off anyway. One wording
    serves the stove and the cupboard alike.
    """
    found = []
    for item in payload.get("extendedIngredients") or ():
        if not isinstance(item, dict):
            continue
        wording = (_text(item.get("original")) or _text(item.get("originalName"))
                   or _text(item.get("name")))
        if wording:
            found.append(RecipeIngredient(wording, item.get("amount"),
                                          _text(item.get("unit")) or None))
    return tuple(found)


def _names(items) -> tuple[str, ...]:
    """The equipment one step calls for, in order and without repeats.

    An equipment name is the kitchen's vocabulary rather than the recipe's -
    a skillet is the word for a skillet - so it may be read out here, and it
    feeds `kitchen.settings.missing_equipment` unchanged.
    """
    found = []
    for item in items or ():
        name = _text(item.get("name")) if isinstance(item, dict) else _text(item)
        if name and name not in found:
            found.append(name)
    return tuple(found)


def _gathered(groups) -> tuple[str, ...]:
    """Every step's equipment as one list, in the order it is first wanted."""
    found = []
    for group in groups:
        for name in group:
            if name not in found:
                found.append(name)
    return tuple(found)


def _trouble(recipe_id, trouble, sentence) -> Method:
    """A method that did not land, carrying what to show in its place."""
    return Method(recipe_id=recipe_id, ok=False, trouble=trouble, sentence=sentence)


def _text(value) -> str:
    """A string off the payload, its whitespace collapsed, or nothing."""
    if not isinstance(value, str):
        return ""
    return _SPACES.sub(" ", value).strip()


def _whole(value) -> int | None:
    """A count the service sends as an int, as a float, or not at all."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(round(value))
