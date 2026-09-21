"""The planner: what the household will eat, decided from what it already has.

`week` plans seven days of lunch and dinner over the tables in
db/migrations/003-the-week.sql. The pantry leads it, one objective function
scores it, and the work it does is bounded before it starts rather than left
to a solver (pm/backlog.md).

A recipe is not ours to keep. What reaches a table here is an integer id on a
live plan row, purged the moment the period closes; the titles, the
instructions and the ingredient text pass through memory and are written
nowhere (docs/db.md).
"""
