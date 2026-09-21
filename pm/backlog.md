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
- **AIoli never buys anything.** It may fill a cart and it may say what a
  basket costs, but the purchase is always a person's click. No item in
  this file may end in a completed order, and no credential that could
  place one belongs in the container. This is a rule, not a default, and
  it does not get relaxed by a later item.
- **The pantry leads the plan.** A week is built from what is already in
  the house first and bought for second. Waste is the thing being
  minimised, and an ingredient already owned and ageing is worth more than
  a cheaper recipe that leaves it to spoil.

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
  the cupboard, with quantity, unit, the date it came in and a rough shelf
  life, editable from the board. Everything downstream reads it: the
  planner searches against it, the grocery list subtracts it, and waste is
  measured against it. The shelf life is what makes ageing stock rank
  ahead of fresh, so it is not an optional column. Cost: a day.

- **The price book does not exist.** Whole Foods and Costco publish no
  API, so a table of the staples actually bought, each with a store, a
  brand, a product as it is labelled on the shelf, a pack size and a
  price, kept current by hand. Pack size is the field that earns it:
  Costco sells in quantities a one-person household cannot finish, and a
  planner that knows only unit price will buy six pounds of salmon to save
  forty cents a pound. Brand and product are what turn "chicken stock"
  into the carton actually bought, so a list is shoppable without standing
  in the aisle deciding again, and they are what a cart would later search
  on. This is the user's own record, so unlike a recipe it may be kept
  indefinitely. Seeded with whatever is bought most often, extended when
  something new appears on a list. Two more columns carry the deals: a
  sale price and the date it runs until, so a thing on offer is a thing
  the planner can reach for while the offer lasts and not after. Cost: a
  day.

- **Nothing plans a week.** The planner proper: lunch and dinner for seven
  days, each recipe cooked once and eaten twice on consecutive days, meals
  the user marked skipped left empty, and the whole plan scored against a
  budget per meal. Servings follow the household setting. The search runs
  from the pantry outward: `complexSearch` with `includeIngredients` set
  to what is in stock and `fillIngredients` on, which is the only call
  that returns used-and-missed alongside the cost and time filters the
  budget and the cadence need. `findByIngredients` with `ranking=2` and
  `ignorePantry=true` is the second pass, for a week that has to use up
  something before it turns. What is on sale in the price book joins that
  search the same way the pantry does, since both are ingredients worth
  building a week around, but the two do not weigh the same: an owned
  ingredient is already paid for and can spoil, a discounted one is
  neither, so the pantry wins where they disagree. Cost: two days; risk:
  the budget, the pantry, the deals
  and the two-day pairing pull against each other, and the first version
  will want a constraint solver before it wants more heuristics.

- **A plan does not become a grocery list.** What the plan needs, minus
  what the pantry holds, resolved against the price book into what to buy
  at which store in which pack size. Minimising waste is the hard half:
  a pack bought for one recipe should be finished by another in the same
  week, so ingredient overlap between chosen recipes is worth more than a
  marginally cheaper recipe in isolation. Ingredient substitutes are the
  lever where an overlap almost lands. Cost: two days.

- **Neither cadence is scheduled.** Two kinds of event, one format. Each
  recipe publishes a ready time, so the plan groups its cooking into at
  most two sessions a week where it can, each session's event carrying the
  summed time of what is cooked in it. The grocery list groups the same
  way into at most two shopping trips, split by store, since Whole Foods
  and Costco are not the same errand. Both come out as `.ics`, and nothing
  consumes them yet - that is a later tool - so they are written to disk
  and served, not sent anywhere. Cost: a day; risk: two trips and two cook
  sessions constrain each other through shelf life, because a Thursday
  shop cannot feed a Monday cook.

- **There is nothing to look at.** The board: the week's plan, which meals
  are skipped, the grocery list by store, the pantry, and the price book.
  Read-only would be half of it, since marking a skip and correcting the
  pantry are both writes. Cost: two days.

- **The list has to be retyped into a cart.** Last, and only once the
  list is trustworthy: fill an Amazon Whole Foods cart from the Whole
  Foods half of the week's list, matching each line to the brand and
  product the price book already names. There is no API for this - see the
  closing section - so it is a browser driven against a signed-in session,
  which makes it the most fragile thing here and the reason it goes last.
  It stops at a filled cart and shows what it put there; the person
  reviews it and buys it, or does not. Cost: three to four days; risk: a
  session that expires, a substitution the store makes silently, and a
  page layout that changes without notice.

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

Neither store publishes its offers either. The Whole Foods weekly flyer
and the Costco coupon book are pages for people to read, not feeds, so a
deal reaches AIoli the way a price does: someone types it in, with the
date it expires. That is the honest version, and it is why the sale
columns sit on the price book rather than in a service of their own.

Amazon Fresh and Whole Foods have no ordering API. Amazon's own support
forum says so plainly; the Amazon Business Ordering API is a different
product for B2B purchasing, and the Product Advertising API's add-to-cart
form does not reach the separate Fresh and Whole Foods cart. A cart is
therefore a browser being driven, never an integration, which is why that
item sits last and why it stops at a filled cart.

Spoonacular's own prices are US averages, not either store's. They are
useful for ranking one recipe against another and not for telling the
user what a basket will ring up to; where the two disagree, the price
book wins.

Neither source publishes what a household actually eats. Whether a plan
was cooked, whether the leftovers were finished, whether a recipe is worth
repeating - none of that arrives from an API, and if it is ever wanted it
has to be asked for on the board.
