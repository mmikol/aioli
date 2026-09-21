"""The client, with urllib stubbed, so a normal run touches no network.

Every test here injects an opener or replaces the module's own, and the one
test that does not is the one asserting the default is urllib. The fixtures
are the invented ones next door; nothing in this file has been anywhere near
the service.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit

import pytest

from recipes import client, fixtures

# A key shaped like one and belonging to nobody, so the assertions about the
# key never leaking have something to look for.
KEY = "not-a-real-key-0000"


class Answer:
    """As much of a urllib response as the client reads."""

    def __init__(self, payload, headers=None):
        self.body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    """A stand-in for urlopen that keeps what it was asked for."""

    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    @property
    def path(self):
        return urlsplit(self.requests[-1].full_url).path

    @property
    def query(self):
        return dict(parse_qsl(urlsplit(self.requests[-1].full_url).query))


class Ledger:
    """The recorder the client injects into, without a database behind it."""

    def __init__(self):
        self.points = 0.0
        self.calls = 0

    def __call__(self, points, calls):
        self.points += points
        self.calls += calls


class Cursor:
    """The two methods the ledger helpers use, and nothing else."""

    def __init__(self, row=None):
        self.row = row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return self.row


def wired(answer, usage=None):
    """A client wired to one canned answer."""
    opener = Opener(answer)
    return client.Spoonacular(key=KEY, usage=usage, opener=opener), opener


def test_complex_search_asks_for_what_the_planner_scores_on():
    chef, opener = wired(Answer(fixtures.COMPLEX_SEARCH))
    payload = chef.complex_search(
        include_ingredients=["notional chickpeas", "make-believe rice"],
        exclude_ingredients=["imaginary parsley"],
        diet="vegetarian", intolerances=["peanut"],
        max_ready_time=45, min_servings=2, max_servings=6, number=2)
    assert opener.path == "/recipes/complexSearch"
    assert opener.query["fillIngredients"] == "true"
    assert opener.query["includeIngredients"] == "notional chickpeas,make-believe rice"
    assert opener.query["excludeIngredients"] == "imaginary parsley"
    assert opener.query["diet"] == "vegetarian"
    assert opener.query["intolerances"] == "peanut"
    assert opener.query["maxReadyTime"] == "45"
    assert opener.query["minServings"] == "2"
    assert opener.query["maxServings"] == "6"
    assert opener.query["number"] == "2"
    assert payload["results"][0]["usedIngredients"]


def test_a_search_without_filters_still_fills_the_ingredients():
    chef, opener = wired(Answer(fixtures.COMPLEX_SEARCH))
    chef.complex_search()
    assert opener.query["fillIngredients"] == "true"
    assert "diet" not in opener.query
    assert "includeIngredients" not in opener.query


def test_nutrition_is_asked_for_only_when_something_will_show_it():
    chef, opener = wired(Answer(fixtures.COMPLEX_SEARCH))
    chef.complex_search()
    assert "addRecipeNutrition" not in opener.query

    chef, opener = wired(Answer(fixtures.COMPLEX_SEARCH_WITH_NUTRITION))
    payload = chef.complex_search(nutrition=True)
    assert opener.query["addRecipeNutrition"] == "true"
    assert payload["results"][0]["nutrition"]["nutrients"]


def test_find_by_ingredients_minimises_what_is_missing():
    chef, opener = wired(Answer(fixtures.FIND_BY_INGREDIENTS))
    payload = chef.find_by_ingredients(["notional chickpeas", "invented lemon"], number=5)
    assert opener.path == "/recipes/findByIngredients"
    assert opener.query["ingredients"] == "notional chickpeas,invented lemon"
    assert opener.query["ranking"] == "2"
    assert opener.query["ignorePantry"] == "true"
    assert opener.query["number"] == "5"
    assert isinstance(payload, list)


def test_information_fetches_the_method_at_the_stove():
    chef, opener = wired(Answer(fixtures.INFORMATION))
    payload = chef.information(9001)
    assert opener.path == "/recipes/9001/information"
    assert "includeNutrition" not in opener.query
    assert payload["instructions"]
    assert payload["readyInMinutes"] == 35


def test_the_key_travels_in_a_header_and_never_in_the_url():
    chef, opener = wired(Answer(fixtures.COMPLEX_SEARCH))
    chef.complex_search(include_ingredients=["invented lemon"])
    request = opener.requests[-1]
    assert request.get_header("X-api-key") == KEY
    assert KEY not in request.full_url


def test_the_key_stays_out_of_what_a_failure_says():
    # A traceback is the likeliest place a secret escapes to, so the message
    # names the path and never the url it was built into.
    chef, _ = wired(HTTPError("https://api.spoonacular.com/x", 500, "boom", {}, None))
    with pytest.raises(client.SpoonacularError) as raised:
        chef.complex_search()
    assert KEY not in str(raised.value)


def test_every_call_is_counted_through_the_injected_ledger():
    ledger = Ledger()
    chef, _ = wired(Answer(fixtures.COMPLEX_SEARCH), usage=ledger)
    chef.complex_search(number=2)
    assert ledger.calls == 1
    assert ledger.points == pytest.approx(client.estimate_points(2))


def test_the_service_is_the_authority_on_what_a_call_cost():
    ledger = Ledger()
    answer = Answer(fixtures.COMPLEX_SEARCH, headers={client.QUOTA_HEADER: "1.53"})
    chef, _ = wired(answer, usage=ledger)
    chef.complex_search()
    assert ledger.points == pytest.approx(1.53)


def test_nutrition_is_estimated_dearer_per_result():
    assert client.estimate_points(10, nutrition=True) > client.estimate_points(10)


def test_a_spent_day_is_its_own_failure():
    ledger = Ledger()
    chef, _ = wired(fixtures.quota_exhausted_error(), usage=ledger)
    with pytest.raises(client.QuotaExhausted) as raised:
        chef.complex_search()
    assert raised.value.status == 402
    # The attempt is in the ledger and costs nothing: the points were gone
    # before the call was made.
    assert ledger.calls == 1
    assert ledger.points == 0


def test_another_refusal_is_not_a_quota_refusal():
    ledger = Ledger()
    chef, _ = wired(HTTPError("https://api.spoonacular.com/x", 500, "boom", {}, None),
                     usage=ledger)
    with pytest.raises(client.SpoonacularError) as raised:
        chef.information(9001)
    assert not isinstance(raised.value, client.QuotaExhausted)
    assert raised.value.status == 500
    assert ledger.calls == 1


def test_a_service_that_cannot_be_reached_spends_nothing():
    ledger = Ledger()
    chef, _ = wired(URLError("no route"), usage=ledger)
    with pytest.raises(client.SpoonacularError) as raised:
        chef.complex_search()
    assert raised.value.status is None
    assert ledger.calls == 1
    assert ledger.points == 0


def test_an_answer_that_is_not_json_is_a_failure_and_not_a_crash():
    class Rubbish(Answer):
        def read(self):
            return b"<html>a proxy said no</html>"

    chef, _ = wired(Rubbish(fixtures.COMPLEX_SEARCH))
    with pytest.raises(client.SpoonacularError):
        chef.complex_search()


def test_a_client_without_a_ledger_still_works():
    # The planner injects one; a script asking a single question need not.
    chef, _ = wired(Answer(fixtures.INFORMATION))
    assert chef.information(9001)["id"] == 9001


def test_a_missing_key_is_a_setup_fault_named_as_one(monkeypatch):
    monkeypatch.delenv("SPOONACULAR_KEY", raising=False)
    with pytest.raises(client.MissingKey):
        client.Spoonacular()


def test_the_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("SPOONACULAR_KEY", KEY)
    chef = client.Spoonacular(opener=Opener(Answer(fixtures.INFORMATION)))
    assert chef.information(9001)["id"] == 9001


def test_the_default_opener_is_urllib(monkeypatch):
    # The one test that does not inject an opener, so the seam the others use
    # is known to be the seam the real client goes out through.
    opener = Opener(Answer(fixtures.COMPLEX_SEARCH))
    monkeypatch.setattr(client, "urlopen", opener)
    client.Spoonacular(key=KEY).complex_search()
    assert opener.requests


def test_the_ledger_rounds_a_fraction_up():
    # The points column is an integer, and overstating makes a run defer early
    # rather than discover a 402 halfway through a week.
    cx = Cursor()
    client.usage_into(cx)(1.02, 1)
    sql, params = cx.executed[-1]
    assert "insert into api_usage" in sql
    assert params[1:] == (2, 1)


def test_a_day_can_be_written_against_a_date_that_is_not_today():
    cx = Cursor()
    client.usage_into(cx, day="2026-09-20")(1.0, 1)
    assert cx.executed[-1][1][0] == "2026-09-20"


def test_remaining_points_reads_the_ledger(monkeypatch):
    monkeypatch.delenv("SPOONACULAR_TIER", raising=False)
    assert client.remaining_points(Cursor({"points": 12})) == 38
    assert client.remaining_points(Cursor((12,))) == 38


def test_a_day_with_no_row_has_the_whole_allowance(monkeypatch):
    monkeypatch.delenv("SPOONACULAR_TIER", raising=False)
    assert client.remaining_points(Cursor(None)) == client.TIER_POINTS["free"]


def test_an_overspent_day_has_nothing_left_rather_than_less_than_nothing():
    assert client.remaining_points(Cursor({"points": 9000}), tier="cook") == 0


def test_the_tier_says_what_a_day_is_worth(monkeypatch):
    monkeypatch.setenv("SPOONACULAR_TIER", "cook")
    assert client.daily_allowance() == 1500
    monkeypatch.delenv("SPOONACULAR_TIER")
    assert client.daily_allowance() == 50
    assert client.daily_allowance("Cook") == 1500
    # An unknown tier is assumed to be the small one, because guessing high is
    # how a run spends points it does not have.
    assert client.daily_allowance("gold") == 50
