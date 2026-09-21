"""The board: the one page the household reads and answers on.

Five views and a router. `chrome` is the vocabulary all of them share - the
document, the escaping, the nav, the route - `pages` holds the three a person
edits, `plan_pages` the two a person reads, and `serve` is the thin router
over http.server that wires their route tables together.

Nothing here owns a table. A view is a plain function of a connection and a
parsed query that hands back a whole document; what it renders comes from the
kitchen and the planner, every write goes through kitchen/moves.py, and the
two questions the router asks a database itself - the healthcheck and the
purge at boot - are asked through the modules that own them.

The board is reachable on the host's loopback and nowhere else, and has no
login: `tailscale serve` is what carries a phone to it (docs/fleet.md).
"""
