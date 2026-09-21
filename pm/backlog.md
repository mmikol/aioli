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
- **Nutrition is shown, not yet optimised.** Spoonacular returns calories
  and macros with the recipe, so the board and the mails carry them and
  the schema stores them. The planner does not read them today: budget and
  waste are the two objectives, and a third pulling against both buys a
  harder solver for a goal nobody has set. "Not yet" rather than "never" -
  a trainer agent is exactly what would hand the chef a protein floor, and
  a schema that dropped the numbers would owe a migration on the day it
  arrived.
- **AIoli is the first of several agents.** An accountant and a trainer
  are expected, and the contract they will all keep is in
  [docs/fleet.md](../docs/fleet.md): own your data, expose MCP tools,
  propose but never complete an irreversible act, run on your own clock,
  emit calendar events. No substrate is shared until a second agent shows
  what is genuinely common.

## Next

- **There is no container yet.** The repo holds a README, a gitignore and
  this file. Nothing can be built until there is a runtime, an image and a
  compose file to run it under. Python 3.12 and PostgreSQL, matching the
  stack next door, so one set of habits covers both. Cost: half a day.

- **Nothing knows what you will not eat.** No diet, no allergy, no
  intolerance, no simple dislike is recorded anywhere, so the planner is
  free to suggest a thing that was never going to be cooked. Spoonacular
  takes `diet`, `intolerances` and `excludeIngredients` on the same search
  the planner already makes, so the cost is a settings table and three
  query parameters. It sits this high because every item below it reads
  the plan it shapes, and retrofitting a filter under a working planner is
  how a week of suggestions gets thrown away. Cost: half a day.

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

- **The pantry has no way to tell the truth.** Nothing decrements it when
  a meal is cooked, increments it when a shop happens, or records that
  Tuesday was a takeaway. Three weeks of that and the table describes a
  kitchen that does not exist, and every promise built on it - the waste
  it minimises, the list it subtracts from, the budget it reports - is
  computed against fiction. So: a cooked, bought, skipped and finished
  event per plan line, each one moving stock, and a standing assumption
  that an unconfirmed meal did not happen rather than that it did. The
  confirmations want asking for at the moment the answer is known, which
  is what the midweek mail below is for. Cost: a day, and it is the
  cheapest day in this file. Risk: ask too often and it gets ignored,
  which is the same as not having it.

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

- **An ingredient is not a product.** "2 cups diced tomatoes" has to
  become "Kirkland diced tomatoes, 28 oz" before it can be priced,
  subtracted from the pantry or put in a cart, and that mapping is fuzzy
  in three ways at once: the wording differs, the units differ, and a
  recipe's amount rarely divides into a pack size. It is currently hidden
  inside the grocery list as though it were an implementation detail; it
  is the crux of the list, the pantry maths and the cart alike, and it
  earns a table of its own - ingredient, product, the conversion between
  their units - plus a way to correct a match by hand, because it will be
  wrong often enough that a silent wrong answer is worse than an asked
  question. Cost: two days.

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

- **Not everything reheats.** Cooking once and eating twice is right for a
  chili and wrong for a fish, a salad or anything fried, and no source
  publishes a keeps-well flag to sort them. Without one the planner will
  confidently pair a thing that is inedible on the second day, which is
  the fastest way to lose trust in the whole plan. A judgement stored per
  recipe, defaulted by category and corrected on the board when a pairing
  turns out badly; a recipe that does not keep is cooked for one meal and
  the pairing rule bends around it. Cost: half a day.

- **The same dinner every week.** A fixed budget, a fixed household and a
  stable pantry give the planner one right answer, and it will keep
  finding it. A table of what has been planned before and a cooldown that
  costs a recent recipe its place, so variety is a constraint rather than
  a hope. Cost: half a day.

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
  pantry are both writes. Calories and macros ride along on each meal,
  shown and never scored. Cost: two days.

- **Nothing runs unattended.** The container keeps its own clock: one
  planning run a week, the mails on their two days, and every run
  idempotent, because a retry that plans the same week twice or moves the
  same stock twice is worse than a run that never happened. A run that
  fails is the real design problem - a quota spent, the API down, a
  network gone - since the failure mode is discovering on Sunday that
  there is no dinner plan. So a failed run still reports, saying what
  broke and what the last good plan was. Cost: half a day.

- **Nothing tells you any of this.** Two mails a week, and they are not
  the same mail twice. Before the shop: the week's plan, the list by
  store, the total against the budget, and the trips and cook sessions as
  things to do. Midweek: what is left, what turns soon, and the
  confirmations the pantry needs to stay true - which is the real job, the
  summary being how it earns the open. SMTP credentials in `.env` beside
  the API key. Cost: a day; risk: a mail nobody reads is a pantry nobody
  corrects, so brevity is a requirement and not a preference.

- **The household's facts are the chef's columns.** Household size, the
  budget, the evenings that are free and what the household will not eat
  are facts about the household, lodged with the chef only because the
  chef exists first. An accountant wants the first two and a trainer the
  last, so they belong in a table of their own rather than scattered as
  columns on whatever needed them. Doing it now is a table; doing it after
  the accountant is a migration and a reconciliation. Cost: half a day.

- **Nothing outside can ask AIoli anything.** The functions the chef
  already has internally - the week's plan, what is in the pantry, the
  grocery list, the cooking sessions - published as MCP tools, read-only
  to start. This is the whole integration story for the fleet, and it is
  nearly free precisely because the functions exist anyway: an accountant
  reconciling a grocery spend should not need to know what a recipe is.
  Worth doing once the planner and the list are real, and not before,
  since a tool over a function that does not work yet is a lie with a
  schema. Cost: half a day.

- **The hand-entered data has no copy.** The price book and the pantry are
  hours of a person's typing and exist nowhere else; a dropped volume
  takes both, and with them every price the budget is computed from. A
  dump to a file the user keeps, on a schedule and on demand, restorable
  into an empty database. Unlike a recipe, this is the user's own record,
  so nothing forbids keeping it. Cost: half a day.

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
