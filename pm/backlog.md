# Backlog

What is worth doing next, why, and what it would cost. Ordered by payoff
over blast radius; the first is the one to pick up.

## Shape of an item

One bullet each: a bold title that states the problem as a sentence, then
prose that says what it is, what it would touch, and what it would cost.
Cost is in human-scale words - an hour, half a day, two days - and a risk
follows it where there is one. Ordering carries the priority, so there is
no priority field; the section carries the status, so there is no status
field. An item is a problem with a payoff, never a wish.

## Settled

The decisions the items below assume, so no item has to restate them.

- **The recipes come from Spoonacular.** It is the only surveyed API that
  publishes a per-serving cost (`/recipes/{id}/priceBreakdownWidget.json`),
  and cost is half the requirements. It also carries meal-plan generation,
  a shopping-list endpoint, ingredient substitutes, and `complexSearch`
  filters on `maxReadyTime`, `minServings` and `maxServings`. Edamam holds
  2.3M recipes to Spoonacular's ~365k and publishes no cost at all, which
  rules it out. The free tier is 50 points a day and will not plan a week;
  Cook at $29 a month gives 1,500.
- **The plan covers lunch and dinner.** Breakfast is out: it is routine
  and does not want suggesting.
- **The household size is a setting, default one.** The planner reads it;
  nothing hard-codes a serving count.
- **The board is a web page in the container.** Marking a meal skipped and
  editing the pantry are both editing, and editing wants a page.
- **Store prices come from a price book the user keeps.** Whole Foods and
  Costco publish no API. See the closing section.

## Next

- **There is no container yet.** The repo holds a README, a gitignore and
  this file. Nothing can be built until there is a runtime, an image and a
  compose file to run it under. Python 3.12 and PostgreSQL, matching the
  stack next door, so one set of habits covers both. Cost: half a day.

- **Nothing pulls a recipe.** A Spoonacular client, its key read from
  `.env` and never committed, over `complexSearch` for suggestions and
  `priceBreakdownWidget` for cost. Two constraints shape it: the terms cap
  caching at one hour and require deleting everything obtained if the key
  goes away, so a recipe is fetched and used, never accumulated into a
  local library; and the points quota is small enough that a wasted call
  is a real cost, so every call is counted and logged. What may be stored
  is what the user owns - the plan that was chosen, the pantry, the price
  book. Cost: a day; risk: a design that treats the API as a database and
  has to be unwound later.

- **The pantry is not written down.** A table of what is in the fridge and
  the cupboard, with quantity, unit and the date it came in, editable from
  the board. Everything downstream reads it: the grocery list subtracts it,
  and waste is measured against it. Cost: a day.

- **The price book does not exist.** Whole Foods and Costco publish no
  API, so a table of the staples actually bought, each with a store, a
  pack size and a price, kept current by hand. Pack size is the field that
  earns it: Costco sells in quantities a one-person household cannot
  finish, and a planner that knows only unit price will buy six pounds of
  salmon to save forty cents a pound. Seeded with whatever is bought most
  often, extended when something new appears on a list. Cost: a day.

- **Nothing plans a week.** The planner proper: lunch and dinner for seven
  days, each recipe cooked once and eaten twice on consecutive days, meals
  the user marked skipped left empty, and the whole plan scored against a
  budget per meal. Servings follow the household setting. Cost: two days;
  risk: the budget and the two-day pairing pull against each other, and
  the first version will want a constraint solver before it wants more
  heuristics.

- **A plan does not become a grocery list.** What the plan needs, minus
  what the pantry holds, resolved against the price book into what to buy
  at which store in which pack size. Minimising waste is the hard half:
  a pack bought for one recipe should be finished by another in the same
  week, so ingredient overlap between chosen recipes is worth more than a
  marginally cheaper recipe in isolation. Ingredient substitutes are the
  lever where an overlap almost lands. Cost: two days.

- **The cooking cadence is not scheduled.** Each recipe publishes a ready
  time; the plan groups them into at most two cooking sessions a week
  where it can, and emits one calendar event per session as an `.ics`
  file. Nothing consumes the file yet - that is a later tool - so it is
  written to disk and served, not sent anywhere. Cost: a day.

- **There is nothing to look at.** The board: the week's plan, which meals
  are skipped, the grocery list by store, the pantry, and the price book.
  Read-only would be half of it, since marking a skip and correcting the
  pantry are both writes. Cost: two days.

## Done

*Empty. A finished item moves up here with the branch or short commit it
landed in, after a spaced hyphen.*

## What the sources do not publish

Bounds on the whole list above, so no item is ever written against them.

Whole Foods and Costco have no public API. Every apparent one found is a
third-party scraper reselling the data - FoodSpark, Actowiz, Oxylabs,
Parse.bot - which costs a second subscription, breaks when either site
changes its markup, and runs against both retailers' terms. So AIoli does
not know a live shelf price and will not claim to: the price book is the
user's own record, and a budget figure is as current as the last time it
was edited.

Spoonacular's own prices are US averages, not either store's. They are
useful for ranking one recipe against another and not for telling the
user what a basket will ring up to; where the two disagree, the price
book wins.

Neither source publishes what a household actually eats. Whether a plan
was cooked, whether the leftovers were finished, whether a recipe is worth
repeating - none of that arrives from an API, and if it is ever wanted it
has to be asked for on the board.
