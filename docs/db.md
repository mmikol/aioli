# The database

AIoli stores one thing: the household's own record. What is owned, what was
consumed, what was paid, what was judged. Recipes are not stored. They are
fetched when needed, shown, and dropped.

That is the API's terms and it is also the better design, because it settles
what belongs here without arguing each table: if a column would hold
something Spoonacular wrote, it does not exist.

## The line

**Never stored.** A recipe's title, description, instructions, ingredient
list, image, nutrition figures, or any text the service authored. Not in a
table, not in a cache past the hour the terms allow, not in a test fixture,
not in a log line, not in a sent mail's archive.

**Stored freely.** What the household owns and does. The pantry. The prices
paid. The meals cooked, skipped and finished. The money spent. What reheats
badly. None of it came from the API; all of it is the user's.

**The single exception, and its limits.** A plan's rows carry a recipe id so
the board can re-fetch a meal while that plan is live. It is a pointer, not
content. It is purged when the plan's period closes, and nothing reads it
afterwards. If that ever feels like a loophole being leaned on, delete the
column and let a closed week show what it consumed rather than what it was
called.

## What follows from the line

Two backlog items assumed a recipe identity that outlives the week, and both
are rewritten to model the household instead. They are better for it.

**Variety** is not "do not repeat recipe 4821"; it is "there has been
chicken thigh three times this month". A cooldown over ingredients and
methods is the household's own eating history, keeps indefinitely, and
catches the thing actually being avoided - the same dinner wearing a
different name.

**Keeps-well** is not a verdict filed against a recipe; it is a rule over
what a dish is made of and how it was cooked. Fried holds badly, a leafy
salad holds badly, a braise holds well. Stated over ingredients and method
it applies to a recipe never seen before, which a per-recipe verdict never
could.

## The tables

| table | holds |
| --- | --- |
| `settings` | one row per household fact - size, budget envelope, diet, cook cadence - each with its value and where it came from |
| `equipment` | what is in the kitchen, so a recipe wanting a pan that is not there can be dropped |
| `pantry` | what is in the house, in two grades: a perishable with quantity, unit, acquired and shelf life; a staple with only in-stock or low |
| `stock_move` | every change to the pantry: bought, cooked, finished, discarded, with what caused it |
| `price_book` | store, brand, product as labelled, pack size, price, sale price, sale until |
| `ingredient_product` | the fuzzy join: an ingredient as a recipe words it, the product it resolves to, the conversion between their units, and whether a person confirmed it |
| `budget_period` | the envelope for a month, what has been spent against it, what rolls forward |
| `plan` | a period, its state, and the run that produced it |
| `plan_meal` | a date, a slot, servings, the pairing, whether it was skipped or cooked, and the live recipe pointer |
| `eating_history` | what was actually eaten, by ingredient and method, which is what variety reads |
| `keeps_well` | the rules over ingredient and method, and the corrections made when a pairing went badly |
| `grocery_line` | what to buy, at which store, in which pack, for which plan |
| `event` | cook sessions and shop trips: when, how long, which `.ics` |
| `run` | the scheduler's ledger: job, the period it covers, started, finished, outcome |
| `api_usage` | points spent per day, so a run can know before it starts whether it can finish |

Fifteen tables, numbered SQL migrations, migrating as it goes. Nothing above
is final; the line above it is.

## What this costs

A closed week cannot show what it was called without asking the API again,
and after the pointer is purged it cannot show it at all. A plan from March
is a record of what was eaten and spent, not a menu to look back over. That
is the trade, and it is the right way round: the pantry, the prices and the
history are the things worth keeping, and they are all ours to keep.
