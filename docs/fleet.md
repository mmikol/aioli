# The fleet

AIoli is the first of several agents, not a program that happens to plan
meals. An accountant and a trainer are expected after it, and eventually
they coordinate. This page says what an agent is, so the second one has
something to conform to rather than a precedent to guess at.

Nothing here describes infrastructure. There is no bus, no registry, no
shared database and no second agent; there is one agent and a contract it
keeps. The contract is written now because it is cheap to keep from the
first commit and expensive to retrofit onto a working system.

## What an agent is

- **It owns its data.** The chef owns the pantry, the price book and the
  plan. No other agent reads them directly; they ask.
- **It exposes its capabilities as MCP tools.** This is the whole
  integration story. `plan_week`, `whats_in_the_pantry`, `grocery_list`
  and `cooking_sessions` are functions the chef needs internally, so
  publishing them costs close to nothing and is what lets an accountant
  reconcile a grocery spend without knowing what a recipe is.
- **It proposes; a person disposes.** See below.
- **It runs on its own clock** and reports its own failures, because an
  agent that fails quietly is worse than one that is not running.
- **It emits calendar events** for anything that consumes a person's time.

## The rule that makes a fleet safe

**No agent completes an irreversible act.** The chef never buys the
groceries, the accountant never moves the money, the trainer never books
the class. Each fills a cart, drafts a transfer, proposes a session, and
shows its work; the person clicks or does not.

This is a property of the fleet, not a quirk of the chef. It is what makes
a set of agents safe to leave running unattended, and it is the one rule
that does not bend for convenience. An agent that needs a credential
capable of an irreversible act does not get one.

## Household, not chef

Some facts belong to the household and are only lodged with the chef
because the chef exists first. They live in their own table so that moving
them out later is a move and not a rewrite.

| fact | who else wants it |
| --- | --- |
| household size | the accountant, for a cost per person |
| the budget | the accountant owns it; the chef spends a slice |
| calendar availability | everyone; the evenings are finite |
| dietary constraints | the chef and the trainer, and they must not diverge |

## The calendar is where agents collide first

Cook sessions, shop trips and workouts compete for the same evenings, and
none of them can be scheduled well while blind to the others. That makes
the calendar the first shared resource worth building, ahead of any shared
database or message bus. For now each agent writes `.ics` and nothing
reads it; when something does, it arbitrates.

## What is deliberately not decided

The substrate - a scheduler, a mailer, a secrets store, a model endpoint -
is duplicated in each agent until a second agent shows which parts are
genuinely common. One example is not a pattern, and a shared library
designed against a single caller is a guess. The extraction happens when
the accountant makes the overlap real.
