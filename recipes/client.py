"""The Spoonacular client - fetch a recipe, count what it cost, keep nothing.

The key travels in a header rather than the query string, so no url written
to a log, a proxy or a traceback carries it. Nothing that comes back is
written anywhere and nothing is cached to disk: a search is used to make a
plan and then dropped, which is the terms' one-hour rule taken at its word
(docs/db.md). Where an hour of holding is worth having - the method at the
stove, so a reload is free - it belongs in the process that is showing it,
not here.

The quota is the other thing that shapes this. The free tier is 50 points a
day and will not plan a week; Cook is 1500. A wasted call is a real cost, so
every attempt is counted through a recorder the caller injects, which keeps
the client testable without a database. `usage_into` binds a connection to
that recorder and `remaining_points` is what the scheduler asks before it
starts, because half a planned week is worse than an honest postponement.
"""
import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.spoonacular.com"

# What a day is worth. Free will not plan a week; Cook is the tier this is
# written against and the one the key will be bought on.
TIER_POINTS = {"free": 50, "cook": 1500}

# The service charges a point for the request and a fraction for each result,
# more when nutrition rides along. It says what a call cost in a header and
# that header is the authority; these are only what to assume without it.
BASE_POINTS = 1.0
POINTS_PER_RESULT = 0.01
POINTS_PER_RESULT_WITH_NUTRITION = 0.025

# The header the service answers with, and the one thing worth reading off a
# response that is otherwise not ours to keep.
QUOTA_HEADER = "X-API-Quota-Request"


class SpoonacularError(Exception):
    """The service refused, or never answered. Carries a status where there is one."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class QuotaExhausted(SpoonacularError):
    """HTTP 402: the day's points are gone.

    Its own type because the scheduler treats it differently from every other
    failure - it defers the run and says so, rather than planning half a week
    and leaving the rest to be noticed on Wednesday.
    """


class MissingKey(SpoonacularError):
    """No key in the environment, which is a setup fault and not a service one."""


class Spoonacular:
    """The one way out to the service.

    `usage` is called after every attempt as `usage(points, calls)`, so the
    ledger is the caller's business and the client needs no database to be
    tested. `opener` stands in for `urllib.request.urlopen` and is how the
    tests keep the network out of a normal run.
    """

    def __init__(self, key=None, usage=None, opener=None, timeout=15.0, base=BASE):
        key = key or os.environ.get("SPOONACULAR_KEY")
        if not key:
            raise MissingKey("SPOONACULAR_KEY is not set")
        self._key = key
        self._usage = usage
        self._opener = opener or urlopen
        self._timeout = timeout
        self._base = base.rstrip("/")

    def complex_search(self, *, include_ingredients=None, exclude_ingredients=None,
                       diet=None, intolerances=None, max_ready_time=None,
                       min_servings=None, max_servings=None, number=10, nutrition=False):
        """What to suggest, searched from the pantry outward.

        `fillIngredients` is not a parameter the caller gets to turn off: it is
        what returns used, missed and unused alongside the time filter, and the
        planner scores on all of them. Nutrition is asked for when the board or
        a mail is going to show it - shown, never scored - and costs more per
        result, which is why it is not simply always on.
        """
        params = {"fillIngredients": "true", "number": number}
        if include_ingredients:
            params["includeIngredients"] = _joined(include_ingredients)
        if exclude_ingredients:
            params["excludeIngredients"] = _joined(exclude_ingredients)
        if diet:
            params["diet"] = _joined(diet)
        if intolerances:
            params["intolerances"] = _joined(intolerances)
        if max_ready_time is not None:
            params["maxReadyTime"] = int(max_ready_time)
        if min_servings is not None:
            params["minServings"] = int(min_servings)
        if max_servings is not None:
            params["maxServings"] = int(max_servings)
        if nutrition:
            params["addRecipeNutrition"] = "true"
        return self._get("/recipes/complexSearch", params, nutrition=nutrition)

    def find_by_ingredients(self, ingredients, *, number=10):
        """The second pass, for a week that has to use something up.

        `ranking=2` minimises what is missing rather than maximising what is
        used, which is the question being asked when a chicken turns on
        Wednesday. `ignorePantry` keeps the service from assuming a cupboard of
        staples this household may not have: the pantry table is the only
        pantry here.
        """
        params = {"ingredients": _joined(ingredients), "number": number,
                  "ranking": 2, "ignorePantry": "true"}
        return self._get("/recipes/findByIngredients", params)

    def information(self, recipe_id, *, nutrition=False):
        """The method, fetched at the moment of cooking because it may not be kept.

        This is the one call made while someone is standing in the kitchen, so
        a failure here costs more trust than a failure anywhere else and is the
        caller's to state plainly rather than paper over with a blank card.
        """
        params = {}
        if nutrition:
            params["includeNutrition"] = "true"
        return self._get(f"/recipes/{int(recipe_id)}/information", params, nutrition=nutrition)

    def _get(self, path, params, nutrition=False):
        """One request, its answer parsed, and what it cost recorded either way."""
        url = f"{self._base}{path}?{urlencode(params)}" if params else self._base + path
        request = Request(url, headers={"x-api-key": self._key, "Accept": "application/json"})
        try:
            with self._opener(request, timeout=self._timeout) as response:
                body = response.read()
                headers = getattr(response, "headers", None)
        except HTTPError as error:
            # A refusal still reached the service, so it still gets a line in
            # the ledger. A 402 is the one refusal that costs nothing: the
            # points were already gone before the call was made.
            fallback = 0.0 if error.code == 402 else BASE_POINTS
            self._spend(_points_spent(getattr(error, "headers", None), fallback))
            if error.code == 402:
                raise QuotaExhausted(
                    f"the day's points are spent; {path} was refused", status=402) from error
            raise SpoonacularError(
                f"{path} failed with HTTP {error.code}", status=error.code) from error
        except URLError as error:
            # Nothing was spent because nothing landed, but the attempt is
            # still worth counting: a run that cannot reach the service at all
            # should read as tried, not as never started.
            self._spend(0.0)
            raise SpoonacularError(f"{path} could not be reached: {error.reason}") from error
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError as error:
            self._spend(_points_spent(headers, BASE_POINTS))
            raise SpoonacularError(f"{path} answered with something that is not JSON") from error
        self._spend(_points_spent(headers, estimate_points(_result_count(payload), nutrition)))
        return payload

    def _spend(self, points, calls=1):
        """Hand the cost to whoever is keeping the ledger, if anyone is."""
        if self._usage is not None:
            self._usage(points, calls)


def estimate_points(results, nutrition=False):
    """What a call of this size costs, for when the service does not say.

    Rounded towards spending more rather than less: a planner that thinks it
    has fewer points defers, and one that thinks it has more half-plans a week.
    """
    per = POINTS_PER_RESULT_WITH_NUTRITION if nutrition else POINTS_PER_RESULT
    return BASE_POINTS + per * max(0, int(results))


def usage_into(cx, day=None):
    """A recorder bound to a connection, to hand to `Spoonacular(usage=...)`.

    The ledger counts in whole points and the service charges fractions, so a
    call rounds up. Overstating makes a run defer early, which is the harmless
    direction to be wrong in.

    The caller commits, and wants to commit this even when the run it belongs
    to fails: the points went whether or not the week got planned, and a
    ledger that rolls back with the work spends them twice.
    """
    def record(points, calls):
        cx.execute(
            "insert into api_usage (day, points, calls)"
            " values (coalesce(%s::date, current_date), %s, %s)"
            " on conflict (day) do update set"
            " points = api_usage.points + excluded.points,"
            " calls = api_usage.calls + excluded.calls",
            (day, math.ceil(points), calls))

    return record


def spent_today(cx, day=None):
    """What the ledger says has gone today."""
    row = cx.execute("select points from api_usage where day = coalesce(%s::date, current_date)",
                     (day,)).fetchone()
    if row is None:
        return 0
    # db.psql hands out dict rows; a caller with its own factory is not turned
    # away for it, since this is the one thing the scheduler has to be able to
    # ask on any connection it has.
    return row["points"] if isinstance(row, dict) else row[0]


def daily_allowance(tier=None):
    """What the tier in force allows in a day. SPOONACULAR_TIER, or free."""
    name = (tier or os.environ.get("SPOONACULAR_TIER") or "free").strip().lower()
    return TIER_POINTS.get(name, TIER_POINTS["free"])


def remaining_points(cx, tier=None, day=None):
    """What is left today, which is what a run asks itself before it begins.

    Never negative: a run that has overspent has nothing to plan with, and
    a negative number only invites arithmetic that reads as if it did.
    """
    return max(0, daily_allowance(tier) - spent_today(cx, day))


def _points_spent(headers, fallback):
    """What the service says the call cost, or what to assume when it is silent."""
    raw = headers.get(QUOTA_HEADER) if headers is not None else None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _result_count(payload):
    """How many recipes came back, which is what the fractional charge is per."""
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return len(payload["results"])
    return 1


def _joined(values):
    """A comma-separated list, since the pantry arrives here as a list of ours."""
    if isinstance(values, str):
        return values
    return ",".join(str(value).strip() for value in values if str(value).strip())
