"""The boot: where the database is, and the guards that stop two migrations
claiming the same number.

Both guards run before any SQL does, which is the whole point of them: a
second 004 that reached the database would either collide on the primary key
and roll the boot back with a traceback naming neither file, or - once the
first had been applied - be skipped in silence, leaving every table it was
meant to create missing while `pending` reported nothing wrong.
"""
import pytest

from db import psql


def migrations(tmp_path, files):
    """A migrations directory of this test's own making."""
    for name, sql in files.items():
        (tmp_path / name).write_text(sql, encoding="utf-8")
    return tmp_path


def test_the_database_is_the_one_the_environment_names(monkeypatch):
    monkeypatch.setenv("AIOLI_DATABASE_URL", "postgresql://someone@elsewhere/aioli")
    assert psql.dsn() == "postgresql://someone@elsewhere/aioli"
    monkeypatch.delenv("AIOLI_DATABASE_URL")
    # The stack's own, so a container that was handed nothing still finds the
    # database beside it.
    assert psql.dsn() == psql.DEFAULT_DSN


@pytest.mark.database
def test_reading_what_is_applied_does_not_write_anything(db, monkeypatch, tmp_path):
    # /health asks this on every check. A reader that created
    # schema_migrations would be a GET shaping the schema.
    db.execute("drop table schema_migrations")
    monkeypatch.setattr(psql, "MIGRATIONS", migrations(tmp_path, {}))
    assert psql.applied(db) == set()
    assert db.execute(
        "select to_regclass('schema_migrations') as found").fetchone()["found"] is None
    assert psql.pending(db) == []


@pytest.mark.database
def test_two_migrations_claiming_one_number_are_refused_by_name(db, monkeypatch, tmp_path):
    monkeypatch.setattr(psql, "MIGRATIONS", migrations(tmp_path, {
        "004-the-pantry.sql": "create table one_thing (id integer);",
        "004-the-week.sql": "create table another_thing (id integer);"}))
    with pytest.raises(ValueError) as refused:
        psql.pending(db)
    # Both names, because the useful question is which two files collided.
    assert "004-the-pantry.sql" in str(refused.value)
    assert "004-the-week.sql" in str(refused.value)
    assert db.execute("select to_regclass('one_thing') as found").fetchone()["found"] is None


@pytest.mark.database
def test_a_file_that_is_not_a_migration_is_refused_rather_than_skipped(db, monkeypatch, tmp_path):
    monkeypatch.setattr(psql, "MIGRATIONS", migrations(tmp_path, {
        "notes.sql": "create table a_thing (id integer);"}))
    with pytest.raises(ValueError, match="notes.sql"):
        psql.pending(db)


@pytest.mark.database
def test_a_container_that_starts_twice_migrates_once(db, monkeypatch, tmp_path):
    monkeypatch.setattr(psql, "MIGRATIONS", migrations(tmp_path, {
        "004-a-thing.sql": "create table a_thing (id integer);"}))
    assert psql.migrate(db) == ["004-a-thing.sql"]
    assert db.execute("select to_regclass('a_thing') as found").fetchone()["found"] is not None
    # The second boot has nothing to do, which is what `schema_migrations` is
    # for: the image and the database agree about where the schema is.
    assert psql.migrate(db) == []
    assert psql.pending(db) == []


@pytest.mark.database
def test_the_migrations_are_applied_oldest_first_whatever_the_filenames_sort_to(
        db, monkeypatch, tmp_path):
    # Ordering is by the parsed number and not by the name, because 10 sorts
    # before 9 as text and a migration applied out of order is a table built
    # on one that does not exist yet.
    monkeypatch.setattr(psql, "MIGRATIONS", migrations(tmp_path, {
        "009-the-first.sql": "create table first_thing (id integer primary key);",
        "010-the-second.sql":
            "create table second_thing (id integer references first_thing);"}))
    assert psql.migrate(db) == ["009-the-first.sql", "010-the-second.sql"]
