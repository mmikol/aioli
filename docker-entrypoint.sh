#!/bin/sh
# The role is the first argument. Every role migrates first: the schema is
# the one thing they all agree about. There is no `test` role: pytest is not
# in the image, and the suite is run from a checkout against the database the
# stack publishes (README.md).
set -e

case "$1" in
  migrate) exec python -m db.psql migrate ;;
  board)
    python -m db.psql migrate
    # 0.0.0.0 inside the container, and nowhere near the network for it:
    # compose publishes the port on the host's loopback only, and a bind to
    # the container's own loopback would make that published port unreachable
    # (compose.yaml).
    exec python -m board.serve --host 0.0.0.0 --port 8018
    ;;
  *) exec "$@" ;;
esac
