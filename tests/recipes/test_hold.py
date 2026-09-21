"""The hour: that it is kept off a clock rather than off traffic, that it is
bounded by count as well as by age, and that what it holds reaches nothing but
this process.

The clock is injected everywhere, because an hour is not worth waiting out.
The one test that cannot inject it is the one about the sweeping thread, which
waits on a hold told to sweep every hundredth of a second.
"""
import inspect
import time

from recipes import hold as held


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def forward(self, seconds):
        self.now += seconds


def a_hold(**how):
    """A hold on a clock the test owns, sweeping only when it is asked to."""
    clock = Clock()
    return held.Hold(clock=clock, sweep_every=3600, **how), clock


def test_what_is_held_comes_back_inside_the_hour():
    hold, clock = a_hold()
    hold.put(9001, "the method")
    clock.forward(59 * 60)
    assert hold.get(9001) == "the method"
    assert len(hold) == 1


def test_the_hour_ends_exactly_where_the_terms_put_it():
    hold, clock = a_hold()
    hold.put(9001, "the method")
    clock.forward(held.HOLD_SECONDS - 1)
    assert hold.get(9001) == "the method"
    clock.forward(1)
    assert hold.get(9001) is None
    assert len(hold) == 0


def test_a_hold_longer_than_the_hour_cannot_be_asked_for():
    # The one number here that is somebody else's rule is not reachable by a
    # keyword argument.
    hold, clock = a_hold(hold_seconds=24 * 3600)
    hold.put(9001, "the method")
    clock.forward(held.HOLD_SECONDS)
    assert hold.get(9001) is None


def test_nothing_is_held_past_the_hour_though_nobody_ever_asks_again():
    # The terms cap what may sit in memory and not what may be answered from
    # it, so the thread is what makes the hour true of a quiet process. Every
    # public way of asking sweeps as a side effect of being asked, so this is
    # the one test that reads the hold directly - asking would be doing the
    # work the sweeping is supposed to have done.
    clock = Clock()
    hold = held.Hold(clock=clock, sweep_every=0.01)
    hold.put(9001, "the method")
    clock.forward(held.HOLD_SECONDS)
    waited = time.monotonic() + 5
    while hold._kept and time.monotonic() < waited:
        time.sleep(0.01)
    assert hold._kept == {}
    hold.stop()


def test_the_count_bound_pushes_out_the_least_recently_wanted():
    hold, _ = a_hold(hold_at_most=2)
    hold.put(9001, "one")
    hold.put(9002, "two")
    hold.get(9001)                     # the pan this is actually about
    hold.put(9003, "three")
    assert hold.get(9001) == "one"
    assert hold.get(9002) is None
    assert len(hold) == 2


def test_forgetting_drops_one_or_all_of_them():
    hold, _ = a_hold()
    hold.put(9001, "one")
    hold.put(9002, "two")
    hold.forget(9001)
    assert len(hold) == 1
    hold.forget()
    assert len(hold) == 0


def test_stopping_drops_everything_and_ends_the_sweeping():
    hold = held.Hold(clock=Clock(), sweep_every=0.01)
    hold.put(9001, "one")
    hold.stop()
    assert len(hold) == 0
    hold._sweeper.join(timeout=5)
    assert not hold._sweeper.is_alive()


def test_the_hold_reaches_neither_the_database_nor_the_disk():
    # The rule this module exists to keep, asserted against the module itself
    # rather than trusted: what is held here is the service's text, and it may
    # live in this process and nowhere else (docs/db.md).
    source = inspect.getsource(held)
    for forbidden in ("from db", "import db", "psql", "open(", "pathlib", "sqlite", "logging"):
        assert forbidden not in source
