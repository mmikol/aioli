"""The kitchen: what the household has decided, what it owns, and what it did.

Three modules over the tables in db/migrations/001-the-household.sql.
`settings` is the household's facts - its size, its cadence, what it will not
eat, what it cooks with. `pantry` is what is in the house. `moves` is the
ledger that keeps the pantry honest, and it is the only way the pantry is
written to as meals are cooked and shops happen.

Everything here is the household's own record, so unlike a recipe it may be
kept indefinitely (docs/db.md).
"""
