"""The connection, and the migrations that shape what it connects to.

One dsn, read from the environment, defaulting to the compose stack's own
database. Migrations are numbered SQL files applied in order and recorded
in `schema_migrations`, so a container that starts twice migrates once.
"""
import os
import pathlib
import re
from typing import Any

import psycopg

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"

DEFAULT_DSN = "postgresql://aioli:aioli@db/aioli"

# A row as every reader in this repo gets one. `connect` asks psycopg for dict
# rows, so a column is reached by its name; the values are whatever a column's
# type maps to, which is the only reason this is not narrower.
Row = dict[str, Any]


def dsn() -> str:
    """The database to talk to. AIOLI_DATABASE_URL, or the stack's own."""
    return os.environ.get("AIOLI_DATABASE_URL") or DEFAULT_DSN


def connect(url: str | None = None) -> psycopg.Connection:
    """A connection, with rows as dicts: every caller here wants names."""
    return psycopg.connect(url or dsn(), row_factory=psycopg.rows.dict_row)


# Where the applied migrations are recorded. `migrate` creates it, and
# nothing else does: a board answering /health is a read, and a read is not
# the thing that should be shaping a schema.
LEDGER = ("create table if not exists schema_migrations ("
          " version integer primary key,"
          " name text not null,"
          " applied_at timestamptz not null default now())")


def applied(cx) -> set[int]:
    """The migrations this database has already seen, by number.

    A read, and only a read. `schema_migrations` may not exist yet - a fresh
    database, or one nobody has migrated - and that answers as nothing
    applied rather than as a table being created by whoever asked.
    """
    if cx.execute("select to_regclass('schema_migrations') as found").fetchone()["found"] is None:
        return set()
    return {r["version"] for r in cx.execute(
        "select version from schema_migrations").fetchall()}


def pending(cx) -> list[tuple[int, pathlib.Path]]:
    """The migration files not yet applied, oldest first.

    Ordering is by the parsed version and not by the filename, and a repeated
    version is refused before any SQL runs. Both matter because migrations
    arrive from several hands at once: two people each adding an 004 is the
    ordinary accident. The second file would either collide on the primary
    key and roll the whole boot back with a traceback naming neither file,
    or - worse, once the first had been applied - be skipped in silence,
    leaving every table it was meant to create missing while `pending`
    reported nothing wrong.
    """
    done = applied(cx)
    found, seen = [], {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        named = re.fullmatch(r"(\d+)-.+\.sql", path.name)
        if not named:
            raise ValueError("%s is not a migration: the name wants <number>-<what-it-does>.sql"
                             % path.name)
        version = int(named.group(1))
        if version in seen:
            raise ValueError("two migrations claim %d: %s and %s"
                             % (version, seen[version], path.name))
        seen[version] = path.name
        if version not in done:
            found.append((version, path))
    found.sort(key=lambda pair: pair[0])
    return found


def tables(cx) -> int:
    """How many tables the schema holds.

    What the container's healthcheck counts, so that the one question it asks
    about shape is asked in the module that owns the connection rather than in
    the board (board/serve.py).
    """
    return cx.execute("select count(*) as n from information_schema.tables"
                      " where table_schema = 'public'").fetchone()["n"]


def migrate(cx) -> list[str]:
    """Apply what is pending. Returns the names applied, oldest first.

    Each migration runs in the caller's transaction and records itself in
    the same one, so a failure leaves neither the change nor the claim that
    it happened. `schema_migrations` is created here, because this is the
    one caller that is entitled to write.
    """
    cx.execute(LEDGER)
    ran = []
    for version, path in pending(cx):
        cx.execute(path.read_text(encoding="utf-8"))
        cx.execute("insert into schema_migrations (version, name) values (%s, %s)",
                   (version, path.name))
        ran.append(path.name)
    return ran


def main(argv: list[str] | None = None) -> int:
    """`python -m db.psql migrate` - what the entrypoint calls on boot."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    verb = argv[0] if argv else "migrate"
    with connect() as cx:
        if verb == "migrate":
            ran = migrate(cx)
            cx.commit()
            print("applied %d migration(s)" % len(ran))
            for name in ran:
                print("  " + name)
            return 0
        if verb == "pending":
            for _, path in pending(cx):
                print(path.name)
            return 0
    print("usage: python -m db.psql [migrate|pending]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
