"""The kitchen: what the household has decided, what it owns, and what it did.

Three modules over the tables in db/migrations/001-the-household.sql, all of
them except `api_usage`: that one is the ledger of points spent at the recipe
service, written and read by recipes/client.py, and it sits in 001 because it
is where the schema starts rather than because the kitchen keeps it.
`settings` is the household's facts - its size, its cadence, what it will not
eat, what it cooks with. `pantry` is what is in the house. `moves` is the
ledger that keeps the pantry honest, and it is the only way the pantry is
written to as meals are cooked and shops happen.

Everything here is the household's own record, so unlike a recipe it may be
kept indefinitely (docs/db.md).
"""
from collections.abc import Sequence


def one_of(value: str, allowed: Sequence[str], what: str) -> str:
    """`value` where the vocabulary allows it, and the refusal where it does not.

    Seven closed vocabularies pass through here - a grade, a level, a reason,
    a slot, a source, a dietary rule and the planner's plan state - and the
    first two are checked on both
    sides of a write, because the caller usually decides one before the
    kitchen sees it and an unrecognised word inferred into a plausible row is
    worse than a refusal. Written once so both sides refuse in the same words.
    """
    if value not in allowed:
        raise ValueError("a %s is one of %s, not %r" % (what, ", ".join(allowed), value))
    return value
