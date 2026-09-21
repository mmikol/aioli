#!/bin/sh
# The role is the first argument. Every role migrates first: the schema is
# the one thing they all agree about.
set -e

case "$1" in
  migrate) exec python -m db.psql migrate ;;
  board)
    python -m db.psql migrate
    exec python -m board.serve --host 0.0.0.0 --port 8018
    ;;
  test) shift; exec python -m pytest "$@" ;;
  *) exec "$@" ;;
esac
