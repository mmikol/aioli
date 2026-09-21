# The fleet

AIoli is the first of several agents, not a program that happens to plan
meals. An accountant and a trainer are expected after it, and eventually
they coordinate. This page says what an agent is, so the second one has
something to conform to.

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
  publishing them costs close to nothing and lets an accountant reconcile a
  grocery spend without knowing what a recipe is.
- **It proposes; a person disposes.** See below.
- **It runs on its own clock** and reports its own failures, because an
  agent that fails quietly is worse than one that is not running.
- **It emits calendar events** for anything that consumes a person's time.

## The rule that makes a fleet safe

**No agent completes an irreversible act.** The chef never buys the
groceries, the accountant never moves the money, the trainer never books
the class. Each fills a cart, drafts a transfer, proposes a session, and
shows its work; the person clicks or does not.

This is a property of the fleet, not a quirk of the chef. It makes a set of
agents safe to leave running unattended, and it is the one rule that does
not bend for convenience. An agent that needs a credential capable of an
irreversible act does not get one.

## Household, not chef

Some facts belong to the household and are only lodged with the chef
because the chef exists first. They live in their own table so that moving
them out later is a move and not a rewrite.

| fact | who owns it | what the chef does with it |
| --- | --- | --- |
| household size | the household | reads it; servings follow it |
| the food budget | the accountant, when it exists | reads the period's envelope; splits it across meals itself |
| calendar availability | the household | reads it; schedules around it |
| dietary constraints | the trainer, when it exists | reads it; filters on it |

An agent does not own a value because it optimises against one. The chef is
given a budget per meal and plans inside it; it does not set one, move one
between weeks, or hold an opinion about what the household can afford. What
it gives back is what a plan costs - the number an accountant wants anyway.
Today the budget is typed into the settings table; later it arrives from the
accountant through the same field, and nothing else changes.

The same goes for a protein floor, if a trainer ever sets one: a constraint
the chef honours, never a target the chef chooses.

## The calendar is where agents collide first

Cook sessions, shop trips and workouts compete for the same evenings, and
none of them can be scheduled well while blind to the others. That makes
the calendar the first shared resource worth building, ahead of any shared
database or message bus. For now each agent writes `.ics` and nothing
reads it; when something does, it arbitrates.

## The substrate, when it comes

A shared substrate is wanted: a scheduler, a mailer, a secrets store, a
model endpoint, and a way in by voice or by chat that every agent answers
through. It is not built yet, and the reason is timing. One example is not
a pattern, and a shared library designed against a single caller is a guess
dressed as architecture. The extraction happens when the accountant makes
the overlap real, and what it takes from the chef will be whatever the chef
was already doing plainly.

Keeping that cheap costs nothing now: an agent that owns its data, speaks
over HTTP and MCP, and holds no state in its own process is one that lifts
out. An agent that reaches into another's tables is not.

The same seam carries the voice question. A HomePod cannot run code and
Siri intents want an iOS app, so the way in is a Shortcut calling an agent
over the tailnet and speaking the reply. That is a few endpoints worded for
speech, and the agent that answers "what am I cooking tonight" answers it
the same way the accountant will answer "what did I spend on food".
