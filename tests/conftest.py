"""Shared fixtures.

Two kinds of test:

    unit        pure functions - no database, no network
    database    marked `database`, handed a migrated schema, rolled back after

The second connects through db.psql, so the suite exercises the same
connection and the same migrations the container boots with. AIOLI_NO_DATABASE
runs the suite with no database at all, which is what CI does; so does a
database that is simply not there, because a developer without the stack up
should get skips and not a wall of errors.
"""
import os
import uuid

import pytest

# A test run on the host is not on the compose stack's network, so `db` does
# not resolve. The stack publishes the same database on the loopback, which is
# the one address a host-side run can reach.
HOST_DSN = "postgresql://aioli:aioli@127.0.0.1:5434/aioli"


def _dsn():
    """Where the tests look for a database, or None when told not to look."""
    if os.environ.get("AIOLI_NO_DATABASE"):
        return None
    return _with_timeout(os.environ.get("AIOLI_DATABASE_URL") or HOST_DSN)


def _with_timeout(url, seconds=3):
    """Fail to connect quickly, so a suite with no database skips in a moment
    rather than hanging on the system's own idea of a timeout."""
    if "connect_timeout" in url:
        return url
    return url + ("&" if "?" in url else "?") + "connect_timeout=%d" % seconds


@pytest.fixture
def db():
    """A migrated schema of its own, thrown away when the test ends.

    Everything happens in one transaction that is never committed, so a test
    cannot leave a row behind. The schema is temporary as well as the
    transaction: a database that has already been migrated would otherwise
    hand the test the household's real pantry, and a test that passes against
    someone's groceries is a test that fails on a fresh machine.
    """
    url = _dsn()
    if url is None:
        pytest.skip("AIOLI_NO_DATABASE is set")
    import psycopg
    from psycopg import sql

    from db import psql

    try:
        cx = psql.connect(url)
    except psycopg.Error as error:
        pytest.skip("no database at %s: %s" % (url.split("@")[-1], error))
    schema = sql.Identifier("test_" + uuid.uuid4().hex[:12])
    try:
        cx.execute(sql.SQL("create schema {}").format(schema))
        cx.execute(sql.SQL("set search_path to {}").format(schema))
        psql.migrate(cx)
        yield cx
    finally:
        cx.rollback()
        cx.close()
