"""The stove: the fetch, the hour, the bound, and what it says when it cannot.

Two things are injected everywhere here. The opener, so a normal run touches
no network, and the clock, so the hour is tested by moving it rather than by
waiting out an hour of somebody's afternoon. Nothing in this file has been
near the service: every word of a recipe in it comes from the invented
fixtures next door.
"""
import inspect
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from matching.ingredients import RecipeIngredient
from recipes import client, fixtures, hold, steps

# A key shaped like one and belonging to nobody.
KEY = "not-a-real-key-0000"

# The fixture's own invented method, borrowed for the tests that need a
# recipe worded some other way. Inventing more text here would be a second
# place recipe words live, and fixtures.py is meant to be the only one.
INVENTED = fixtures.INFORMATION["analyzedInstructions"][0]["steps"]


class Reply:
    """As much of a urllib response as the client reads."""

    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")
        self.headers = {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Service:
    """A urlopen that answers with what it was handed and counts the asking.

    The answer may be a payload, an exception to raise, or a callable taking
    the call number, which is how a test says "down once, then up".
    """

    def __init__(self, answer=None):
        self.answer = fixtures.INFORMATION if answer is None else answer
        self.calls = 0
        self.paths = []

    def __call__(self, request, timeout=None):
        self.calls += 1
        self.paths.append(urlsplit(request.full_url).path)
        answer = self.answer(self.calls) if callable(self.answer) else self.answer
        if isinstance(answer, Exception):
            raise answer
        return Reply(answer)


class Clock:
    """A clock the test moves by hand, because an hour is not worth waiting."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def forward(self, seconds):
        self.now += seconds


def wired(answer=None, **held):
    """A stove wired to a stubbed service and a clock the test owns."""
    service = Service(answer)
    clock = Clock()
    chef = client.Spoonacular(key=KEY, opener=service)
    return steps.Stove(chef, clock=clock, **held), service, clock


def test_the_stove_gets_the_steps_the_ready_time_and_the_lines():
    kitchen, service, _ = wired()
    method = kitchen.method(9001)
    assert method.ok and bool(method) and not method.trouble
    assert service.paths == ["/recipes/9001/information"]
    assert method.recipe_id == 9001
    assert method.ready_minutes == 35
    assert method.servings == 4
    assert [step.number for step in method.steps] == [1, 2]
    assert method.steps[0].text == INVENTED[0]["step"]
    chickpeas = fixtures.NOTIONAL_CHICKPEAS
    assert method.lines[0] == RecipeIngredient(chickpeas["original"], 1.0, "can")
    assert all(isinstance(line, RecipeIngredient) for line in method.lines)


def test_the_equipment_comes_out_so_the_kitchen_can_be_asked_about_it():
    kitchen, _, _ = wired()
    method = kitchen.method(9001)
    assert method.steps[0].equipment == ("frying pan",)
    assert method.equipment == ("frying pan",)


def test_a_reload_inside_the_hour_spends_nothing():
    kitchen, service, clock = wired()
    first = kitchen.method(9001)
    clock.forward(59 * 60)
    again = kitchen.method(9001)
    assert service.calls == 1
    assert again is first


def test_the_hold_ends_at_the_hour_exactly():
    kitchen, service, clock = wired()
    kitchen.method(9001)
    clock.forward(steps.HOLD_SECONDS - 1)
    kitchen.method(9001)
    assert service.calls == 1
    clock.forward(1)
    kitchen.method(9001)
    assert service.calls == 2


def test_nothing_is_held_past_the_hour_even_unasked_for():
    # The hour is the terms' rule about what may sit in memory, not about
    # what may be answered from it, so an expired method has to go whether or
    # not anybody opens that meal again.
    kitchen, _, clock = wired()
    kitchen.method(9001)
    assert kitchen.held() == 1
    clock.forward(steps.HOLD_SECONDS)
    assert kitchen.held() == 0


def test_the_hour_at_the_stove_runs_off_a_clock_and_not_off_the_next_question():
    # The board keeps one stove for the life of the process, and a Wednesday
    # nobody cooks on asks it nothing: a hold swept only when somebody opens a
    # meal would keep Tuesday's method resident for as long as that lasts,
    # which is not what the terms cap (docs/db.md). The hold is read directly
    # because every way of asking it sweeps as a side effect of being asked,
    # and sweeping is the thing under test.
    kitchen, _, clock = wired(sweep_every=0.01)
    kitchen.method(9001)
    kept = kitchen._kept
    assert isinstance(kept, hold.Hold)
    clock.forward(steps.HOLD_SECONDS)
    waited = time.monotonic() + 5
    while kept._kept and time.monotonic() < waited:
        time.sleep(0.01)
    assert kept._kept == {}
    kitchen.stop()


def test_the_points_spent_at_the_pan_reach_the_ledger(monkeypatch):
    # A stove lives for the process and a connection lives for one request, so
    # the recorder arrives with the question. A fetch nobody counted is a
    # planning run told it has a day's quota it has already spent.
    service = Service()
    monkeypatch.setattr(steps, "Spoonacular",
                        lambda **wired_with: client.Spoonacular(
                            key=KEY, opener=service, **wired_with))
    kitchen = steps.Stove(clock=Clock())
    spent = []
    kitchen.method(9001, lambda points, calls: spent.append((points, calls)))
    assert spent == [(1.01, 1)]
    # The hold spends nothing, so it records nothing.
    kitchen.method(9001, lambda points, calls: spent.append((points, calls)))
    assert len(spent) == 1


def test_a_refusal_at_the_pan_reaches_the_ledger_too(monkeypatch):
    # The service was reached and answered, so the attempt is counted whatever
    # it answered: a run that reads the ledger should see the asking.
    service = Service(fixtures.quota_exhausted_error())
    monkeypatch.setattr(steps, "Spoonacular",
                        lambda **wired_with: client.Spoonacular(
                            key=KEY, opener=service, **wired_with))
    kitchen = steps.Stove(clock=Clock())
    spent = []
    assert kitchen.method(9001, lambda points, calls: spent.append((points, calls))).trouble
    assert spent == [(0.0, 1)]


def test_a_hold_longer_than_the_hour_cannot_be_asked_for():
    kitchen, service, clock = wired(hold_seconds=24 * 3600)
    kitchen.method(9001)
    clock.forward(steps.HOLD_SECONDS)
    kitchen.method(9001)
    assert service.calls == 2


def test_the_hold_is_bounded_by_count_as_well_as_by_age():
    kitchen, service, _ = wired(hold_at_most=2)
    for recipe_id in (9001, 9002, 9003):
        kitchen.method(recipe_id)
    assert kitchen.held() == 2
    # The oldest was pushed out rather than kept, so asking for it again is a
    # fresh call and not a hit.
    kitchen.method(9001)
    assert service.calls == 4


def test_the_meal_being_cooked_is_the_last_one_pushed_out():
    kitchen, service, _ = wired(hold_at_most=2)
    kitchen.method(9001)
    kitchen.method(9002)
    kitchen.method(9001)               # the pan this is actually about
    kitchen.method(9003)
    assert service.calls == 3
    kitchen.method(9001)
    assert service.calls == 3


def test_forgetting_drops_one_or_all_of_them():
    kitchen, _, _ = wired()
    kitchen.method(9001)
    kitchen.method(9002)
    kitchen.forget(9001)
    assert kitchen.held() == 1
    kitchen.forget()
    assert kitchen.held() == 0


def test_a_spent_quota_is_a_sentence_and_not_an_exception():
    kitchen, _, _ = wired(fixtures.quota_exhausted_error())
    method = kitchen.method(9001)
    assert not method.ok and not method
    assert method.trouble == "quota"
    assert "quota" in method.sentence and method.sentence.endswith(".")
    assert method.steps == ()


def test_a_service_that_cannot_be_reached_says_so():
    kitchen, _, _ = wired(URLError("no route"))
    method = kitchen.method(9001)
    assert method.trouble == "unreachable"
    assert method.sentence


def test_a_refusal_says_what_it_was():
    kitchen, _, _ = wired(HTTPError("https://api.spoonacular.com/x", 503, "no", {}, None))
    method = kitchen.method(9001)
    assert method.trouble == "refused"
    assert "503" in method.sentence


def test_an_answer_that_is_not_a_recipe_is_a_sentence_too():
    kitchen, _, _ = wired(["not a recipe"])
    method = kitchen.method(9001)
    assert not method.ok
    assert method.sentence


def test_a_failure_is_never_held():
    # A minute of the service being down must not read as an hour of
    # blankness to somebody standing at the pan.
    def down_then_up(call):
        return URLError("no route") if call == 1 else fixtures.INFORMATION

    kitchen, service, _ = wired(down_then_up)
    assert not kitchen.method(9001).ok
    assert kitchen.held() == 0
    assert kitchen.method(9001).ok
    assert service.calls == 2


def test_no_key_is_a_sentence_rather_than_a_board_that_will_not_start(monkeypatch):
    monkeypatch.delenv("SPOONACULAR_KEY", raising=False)
    kitchen = steps.Stove(clock=Clock())
    method = kitchen.method(9001)
    assert method.trouble == "no key"
    assert method.sentence


def test_a_recipe_the_service_has_no_method_for_says_so_rather_than_showing_nothing():
    thin = dict(fixtures.INFORMATION, analyzedInstructions=[], instructions="")
    kitchen, _, _ = wired(thin)
    method = kitchen.method(9001)
    assert method.ok
    assert method.steps == ()
    assert method.trouble == "no steps"
    assert method.sentence
    assert method.lines


def test_a_method_written_as_prose_is_still_a_method():
    markup = "<ol><li>%s</li><li>%s &amp; serve</li></ol>" % (
        INVENTED[0]["step"], INVENTED[1]["step"])
    payload = dict(fixtures.INFORMATION, analyzedInstructions=[], instructions=markup)
    kitchen, _, _ = wired(payload)
    method = kitchen.method(9001)
    assert [step.number for step in method.steps] == [1, 2]
    assert method.steps[0].text == INVENTED[0]["step"]
    assert method.steps[1].text.endswith("& serve")
    assert "<" not in method.steps[1].text
    assert method.trouble == ""


def test_the_numbers_run_straight_through_the_named_parts():
    # The service restarts at one for each part; a person at a stove counts
    # through, and the headings still have to survive.
    payload = dict(fixtures.INFORMATION, analyzedInstructions=[
        {"name": "the pretend pan", "steps": [dict(INVENTED[0], number=1)]},
        {"name": "the invented finish", "steps": [dict(INVENTED[1], number=1)]},
    ])
    kitchen, _, _ = wired(payload)
    method = kitchen.method(9001)
    assert [step.number for step in method.steps] == [1, 2]
    assert [step.part for step in method.steps] == ["the pretend pan", "the invented finish"]


def test_two_tabs_opening_the_same_meal_spend_one_point():
    # The board is threaded and a point is a real cost, so the hold is taken
    # under a lock that spans the fetch.
    kitchen, service, _ = wired()
    ready = threading.Barrier(4, timeout=5)
    got = []

    def open_the_meal():
        ready.wait()
        got.append(kitchen.method(9001))

    hands = [threading.Thread(target=open_the_meal) for _ in range(4)]
    for hand in hands:
        hand.start()
    for hand in hands:
        hand.join(timeout=5)
    assert len(got) == 4
    assert service.calls == 1


def test_a_held_method_cannot_be_edited_by_whoever_was_handed_it():
    kitchen, _, _ = wired()
    method = kitchen.method(9001)
    assert isinstance(method.steps, tuple)
    assert isinstance(method.lines, tuple)
    assert isinstance(method.equipment, tuple)


def test_the_hold_reaches_neither_the_database_nor_the_disk():
    # The one rule this module exists to keep, asserted against the module
    # itself rather than trusted: what is held here is the service's text,
    # and it may live in this process and nowhere else (docs/db.md).
    source = inspect.getsource(steps)
    for forbidden in ("from db", "import db", "psql", "open(", "pathlib", "sqlite", "logging"):
        assert forbidden not in source
