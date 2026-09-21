# AIoli

A personal chef assistant. It knows what is in your kitchen, plans a week of
lunches and dinners around it, and says what to buy for the rest.

The point is waste, not recipes. A week is built from what is already in the
house first and bought for second, each dish is cooked once and eaten twice,
and the pantry stays true because cooking and shopping are confirmed rather
than assumed.

## What it does not do

It does not keep recipes. The recipe service's terms cap caching at an hour
and require deleting what was obtained, so a recipe is fetched, used and
dropped. What is stored is the household's own record: the pantry, what was
eaten, what was paid, what was judged. The line is in
[docs/db.md](docs/db.md) and it is the hard rule of this codebase.

It does not buy anything. It will fill a cart one day and show its work; the
purchase is always a person's click. No credential capable of completing an
order belongs in the container.

It is not deployed. Every port binds to 127.0.0.1, and `tailscale serve` on
the host carries a phone to the board.

## Install

- [Docker Desktop](https://www.docker.com/products/docker-desktop/), or any docker with compose v2
- Python 3.12 for the tests and a docker-less run
- A [Spoonacular](https://spoonacular.com/food-api/console) key in `.env` - see `.env.example`

```bash
git clone git@github.com:mmikol/aioli.git && cd aioli
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then put your key in it
```

## Start

```bash
docker compose up -d
```

| | |
| --- | --- |
| the board | **http://localhost:8018** |
| PostgreSQL | localhost:5434 |

The schema migrates on every boot, because an image and a database that
disagree is a failure even while every query still answers.

Without docker:

```bash
.venv/bin/python -m db.psql migrate     # against AIOLI_DATABASE_URL
.venv/bin/python -m board.serve         # the board, http://localhost:8018
.venv/bin/python -m pytest -q           # the suite
.venv/bin/python -m pytest -m contract  # the one test that calls the real API
```

## The shape of it

```
db/          the connection, and numbered migrations
kitchen/     the settings, the pantry in two grades, the ledger of stock
matching/    a recipe's words against the pantry's, and the units between them
recipes/     the one way out: search, and the steps at the stove
planner/     the week, and what to buy for it
board/       the page it is all read and answered on
```

## Where the work is

[pm/backlog.md](pm/backlog.md) is what is worth doing next, in payoff order,
split into the MVP and what waits. [pm/blockers.md](pm/blockers.md) is the
short list of what only a person can provide.

AIoli is the first of several agents; the contract they all keep is in
[docs/fleet.md](docs/fleet.md).
