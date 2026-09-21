"""An hour of memory, bounded twice, kept nowhere else.

The terms cap a cache at an hour and forbid anything the service authored
reaching a table, a file or a mail's archive (docs/db.md). Two places in this
repo want that same hour: the method at the stove, so a phone waking in a
kitchen spends no point, and the grocery list's lookups, so a list read twice
in an aisle is fetched once. One implementation of the rule rather than two -
two would drift, and the half that drifted would be the half holding somebody
else's words for longer than they allow.

The hour is kept by a clock of the hold's own. Sweeping only when somebody
asks answers correctly and still leaves the text resident in a quiet process
for as long as nobody opens another meal, and the terms cap what may sit in
memory rather than what may be answered from it. So a thread of its own sweeps
on the minute, and every way of asking sweeps as well.
"""
import threading
import time
import weakref
from collections import OrderedDict

# The terms cap a cache at an hour, so an hour is the ceiling. It is enforced
# rather than configured: a caller may ask for less and the constructor
# quietly refuses more, because the one number here that is somebody else's
# rule should not be reachable by a keyword argument.
HOLD_SECONDS = 3600

# Thirty-two answers at once. A week is fourteen meals, so this is two weeks
# of opened ones; a held answer is a few kilobytes of text, which makes a full
# hold tens of kilobytes. The number matters less than the fact that there is
# one: an unbounded dict keyed by recipe id is a leak on a host that is also
# running a database.
HELD_AT_MOST = 32

# How often the hour is checked against the clock. A minute, so what is held
# goes within a minute of the hour rather than sitting there until the next
# time somebody opens a meal, which on a quiet week is days. A sweep is a walk
# over thirty-two entries and costs nothing worth naming, and the slack is
# stated rather than hidden: an answer is never given from past the hour,
# because every way of asking sweeps first.
SWEEP_SECONDS = 60


class Hold:
    """What may be remembered for an hour, and nothing that may not.

    `clock` returns seconds and has to be monotonic. The default is
    `time.monotonic` and not `time.time` because a wall clock steps - NTP
    corrects it, a laptop wakes - and an hour measured against a clock that can
    move backwards is an hour that can be outlived. Tests hand in their own
    and never wait.

    The lock is the hold's own and spans nothing but the hold. A caller that
    has to keep two tabs from spending two points for one answer holds a lock
    of its own across the fetch (recipes/steps.py).
    """

    def __init__(self, *, clock=time.monotonic, hold_seconds=HOLD_SECONDS,
                 hold_at_most=HELD_AT_MOST, sweep_every=SWEEP_SECONDS):
        self._clock = clock
        self._hold_seconds = max(0.0, min(float(hold_seconds), float(HOLD_SECONDS)))
        self._hold_at_most = max(1, int(hold_at_most))
        self._kept: OrderedDict[object, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._sweeper = self._sweeping(max(0.01, float(sweep_every)))

    def get(self, key):
        """What is held under a key, or None when it is absent or past the hour."""
        with self._lock:
            self._drop_the_stale()
            found = self._kept.get(key)
            if found is None:
                return None
            # Asking again says which meal is being cooked, so the one asked
            # for is the last to be pushed out.
            self._kept.move_to_end(key)
            return found[1]

    def put(self, key, value) -> None:
        """Hold one answer, pushing out the least recently wanted at the bound."""
        with self._lock:
            self._kept[key] = (self._clock(), value)
            self._kept.move_to_end(key)
            while len(self._kept) > self._hold_at_most:
                self._kept.popitem(last=False)

    def forget(self, key=None) -> None:
        """Drop one entry, or all of them.

        The terms say everything obtained goes when the key does, so saying it
        has to be one call and not a walk over a dict nobody else can see.
        """
        with self._lock:
            if key is None:
                self._kept.clear()
            else:
                self._kept.pop(key, None)

    def sweep(self) -> None:
        """Drop everything past the hour. The thread below calls this on a clock."""
        with self._lock:
            self._drop_the_stale()

    def stop(self) -> None:
        """Stop sweeping and drop everything. What a process says on its way out."""
        self._stopped.set()
        self.forget()

    def __len__(self) -> int:
        """How many answers are being held, once what has expired is gone."""
        with self._lock:
            self._drop_the_stale()
            return len(self._kept)

    def _drop_the_stale(self) -> None:
        """Everything past the hour, under a lock the caller already holds."""
        now = self._clock()
        stale = [key for key, (at, _) in self._kept.items() if now - at >= self._hold_seconds]
        for key in stale:
            del self._kept[key]

    def _sweeping(self, every):
        """The thread that makes the hour true of a quiet process.

        One thread per hold, waiting on an event rather than sleeping, so a
        process that says `stop` does not wait out a minute to exit. The
        reference back is weak: a hold nobody holds any more takes its thread
        with it instead of keeping itself alive to be swept forever.
        """
        held = weakref.ref(self)
        stopped = self._stopped

        def sweeping():
            while not stopped.wait(every):
                hold = held()
                if hold is None:
                    return
                hold.sweep()
                del hold

        thread = threading.Thread(target=sweeping, name="the-hour", daemon=True)
        thread.start()
        return thread
