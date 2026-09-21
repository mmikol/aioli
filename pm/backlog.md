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
- **A lunch may be a dinner's leftovers or its own dish.** The planner
  decides which, on what a dinner yields and how much of it is left, so
  "cooked once, eaten twice" is sometimes one dinner feeding the next
  day's lunch and sometimes a lunch of its own cooked in a batch. A slot
  is therefore filled either by a cook or by a portion of an earlier cook,
  and the schema says which.
- **Prices are deferred; the seams are not.** The MVP knows nothing about
  money: no price book, no budget, no stores, no brands, no pack sizes.
  What it does do is leave the joints where those belong - the pantry
  holds ingredients so products can arrive under them, the grocery list
  holds quantities so prices can hang off them, and the planner scores
  through one objective function so a cost term is an addition and not a
  rewrite. Adding money should be new columns and one more term, never a
  reshaping.
- **There is no API key yet, so fixtures come first.** Everything but the
  live fetch can be built and tested against hand-written fixtures, which
  the terms require anyway. The key arrives when the planner is real
  enough to be worth a paid tier.
- **The repo is public, with CI.** Lint and tests on every push, as next
  door. The code is a meal planner; what is private lives in the database
  and `.env`, neither of which is committed.
- **The rhythm is configuration.** Two shopping trips and two cooking
  sessions a week, on days set in the settings rather than assumed by the
  code, with the trips spread so fresh things arrive nearer to when they
  are cooked.
- **The household size is a setting, default one.** The planner reads it;
  nothing hard-codes a serving count.
- **The board is a web page in the container.** Marking a meal skipped and
  editing the pantry are both editing, and editing wants a page.
- **The board stays on 127.0.0.1; the tailnet does the reaching.** Nothing
  is published and no port is opened. `tailscale serve` on the host
  proxies the board onto the tailnet, so a phone can answer a
  confirmation from anywhere and the container's binding never changes.
  This keeps the deployment story the same as next door: there is no
  deployment.
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
- **The amount is given; the split is the chef's.** The chef is handed an
  envelope for a period - a month, eventually from the accountant, typed
  into the settings until then - and works out for itself what that means
  per meal. Deciding the size of the envelope is not its business; dividing
  one across the meals actually planned is exactly its business, being a
  planning problem. What it hands back is what a plan costs, which is the
  number the accountant wants anyway.
- **AIoli is the first of several agents.** An accountant and a trainer
  are expected, and the contract they will all keep is in
  [docs/fleet.md](../docs/fleet.md): own your data, expose MCP tools,
  propose but never complete an irreversible act, run on your own clock,
  emit calendar events. No substrate is shared until a second agent shows
  what is genuinely common.

## Next: the MVP

The smallest thing that is useful: know what is in the house, plan a
week around it, say what to buy, and stay true as meals are cooked. No
prices, no budget, no stores, no brands - those are the section below,
and the seams that let them in are named where they bite.

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

- **A recipe can want a pan you do not own.** A ready time assumes an
  equipped kitchen, so a recipe calling for a food processor, a stand
  mixer or a Dutch oven is fiction in a kitchen without one, and it is
  fiction that reads as a perfectly good suggestion. A short list of what
  is actually in the kitchen, and a filter that drops what it cannot make.
  Small, and it rides along with the diet settings. Cost: two hours.

- **Nothing pulls a recipe.** A Spoonacular client, its key read from
  `.env` and never committed, over `complexSearch` for suggestions.
  `priceBreakdownWidget` waits for the section below, along with the rest
  of the money. Two constraints shape it: the terms cap
  caching at one hour and require deleting everything obtained if the key
  goes away, so a recipe is fetched and used, never accumulated into a
  local library; and the points quota is small enough that a wasted call
  is a real cost, so every call is counted and logged. What may be stored
  is what the user owns - the plan that was chosen, the pantry, the price
  book. Cost: a day; risk: a design that treats the API as a database and
  has to be unwound later.

- **The tests cannot keep the data they would test against.** The usual
  move is to record a real response and replay it, and the terms forbid
  exactly that: recipe data may not be kept past an hour. So the fixtures
  are written by hand to the shape of the API and are nobody's recipes,
  and a small contract test run on demand - not in CI, which has no key -
  checks that the shape still matches what the service returns. Settle it
  before there is a suite, because a suite built on recorded responses is
  a suite that has to be thrown away. Cost: half a day.

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

- **A recipe's words are not the pantry's words.** "2 cups diced
  tomatoes" has to meet "tomatoes, tinned, 400g" in the cupboard before
  anything can be subtracted, and the match is fuzzy in two ways even
  before money enters: the wording differs and the units differ. So a
  table that maps the one to the other with a conversion, and a way to
  correct a match by hand, since it will be wrong often enough that a
  silent wrong answer is worse than an asked question.

  This is the seam the product layer arrives through. In the MVP both
  sides are ingredients, which is all a pantry needs. When prices come, a
  product - a brand, a pack size, a shelf label - hangs underneath the
  ingredient it satisfies, and nothing above has to change. Cost: a day
  now, another when products land.

- **Nothing plans a week.** The planner proper: lunch and dinner for seven
  days, every dish cooked once and eaten twice - the second serving being
  the next day's lunch where a dinner yields it, or a lunch batch of its
  own where it does not - and the meals marked skipped left empty.
  Servings follow the household setting. The search runs from the pantry
  outward: `complexSearch` with `includeIngredients` set to what is in
  stock and `fillIngredients` on, which is the only call that returns
  used-and-missed alongside the time filter the cadence needs.
  `findByIngredients` with `ranking=2` and `ignorePantry=true` is the
  second pass, for a week that has to use something up before it turns.

  One objective function, and in the MVP it has two terms: how much of the
  pantry a week consumes, weighted towards what turns soonest, and how
  little it must buy. Cost is a third term added later, deals a fourth;
  they change the weights and not the shape. Cost: two days; risk: the
  pantry and the pairing already pull against each other, and a third term
  is the point at which this wants a constraint solver rather than more
  heuristics.

- **A plan does not become a grocery list.** What the plan needs, minus
  what the pantry already holds, in quantities that make sense to carry
  into a shop. No stores, no packs and no prices in the MVP: one list, by
  aisle if anything. Minimising waste is still the half that matters, and
  it works without money - an ingredient bought for one meal should be
  finished by another in the same week, so overlap between the chosen
  dishes is the thing the planner is rewarded for. Ingredient substitutes
  are the lever where an overlap almost lands. Splitting by store and
  rounding to pack sizes are what the price book adds later. Cost: a day.

- **There is nothing to look at.** The board: the week's plan, which meals
  are skipped, the grocery list by store, the pantry, and the price book.
  Read-only would be half of it, since marking a skip and correcting the
  pantry are both writes. Calories and macros ride along on each meal,
  shown and never scored. Cost: two days.

- **At the stove you need the steps, and they may not be kept.** The
  board shows a plan; cooking needs the method, and the terms forbid
  storing it, so the steps are fetched at the moment of cooking. That
  spends quota on a Tuesday evening and fails outright if the service is
  down while someone is standing in the kitchen. The honest handling is to
  fetch on opening a meal, hold it for the hour the terms allow so a
  reload is free, and say plainly when it cannot be had rather than
  showing a blank card. Cost: half a day; risk: it is the one moment the
  whole system is being used in earnest, so failing there costs more trust
  than failing anywhere else.
## After the MVP

Ordered, but not started until the loop above works end to end.

- **A recipe serves four and the household is one.** Eating each recipe
  twice means two servings are wanted, and most recipes yield four to six.
  Scaling down leaves a third of an onion and half a tin of coconut milk,
  which is the waste the whole system exists to prevent arriving through
  the front door. Two halves to it: scale the recipe and book the
  remainder into the pantry as a real item with a real shelf life, so
  something later has a chance to use it; and prefer, where the score is
  close, a recipe whose natural yield divides cleanly into what is wanted.
  Cost: a day.

- **Not everything reheats.** Cooking once and eating twice is right for a
  chili and wrong for a fish, a salad or anything fried, and no source
  publishes a keeps-well flag to sort them. Without one the planner will
  confidently pair a thing that is inedible on the second day, which is
  the fastest way to lose trust in the whole plan. The judgement is a rule
  over what a dish is made of and how it was cooked - fried holds badly, a
  leafy salad holds badly, a braise holds well - and not a verdict filed
  against a recipe, both because a recipe is not ours to keep
  ([docs/db.md](../docs/db.md)) and because a rule applies to a dish never
  seen before, which a verdict cannot. A dish that does not keep is cooked
  for one meal and the pairing bends around it. Corrections go in when a
  pairing turns out badly. Cost: half a day.

- **The same dinner every week.** A fixed budget, a fixed household and a
  stable pantry give the planner one right answer, and it will keep
  finding it. The cooldown runs over what was eaten and not over which
  recipe was chosen - chicken thigh three times this month, braised twice
  running - because the household's eating history is the household's to
  keep, while a recipe is not ([docs/db.md](../docs/db.md)). Reading it
  that way also catches the thing actually worth avoiding, which is the
  same dinner arriving under a different name. Cost: half a day.

- **Nothing survives a week going wrong.** Every item above assumes a
  plan made on Sunday and a week that obeys it. The week that happens has
  a meal cooked, a Tuesday eaten out, and a chicken that turned on
  Wednesday, and by Thursday the plan depends on stock that is gone and
  budget that is spent. Replanning from a partial week is a different
  problem from planning a fresh one: what is cooked stays cooked, what is
  bought stays bought, and only the remainder is solved again. Without it
  the plan is a document that stops being believed on day three, which is
  the difference between a tool and a demonstration. Cost: a day and a
  half; risk: it is tempting to re-run the planner over the whole week,
  which silently rewrites history.

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

- **Nothing turns a month into a meal.** The envelope arrives for a
  period and the planner needs a figure per meal, so something has to
  divide one by the other, and the naive division is wrong in three ways.
  Skipped meals shrink the denominator, so a week with four meals struck
  out is not a week on a quarter of the money. What has already been spent
  this period has to come off the top, which means the confirmed shops are
  an input. And a stocked pantry distorts it, because a meal cooked from
  food bought last month costs the plan nothing this month: the money that
  leaves at the till and the money attributed to a meal are two different
  numbers, and conflating them is how a budget silently double-counts.
  Underspend rolls forward, within a cap, so a lean fortnight does not
  licence a blowout. Cost: a day; risk: the two numbers above, which want
  naming in the schema before either is computed.

- **On the first day it knows nothing.** The pantry is empty, the price
  book is empty, and until both hold something the planner has nothing to
  plan from - which puts hours of typing between installing this and
  getting one useful suggestion, and that is how a personal tool dies
  before it is adopted. So: a starter price book of the twenty or so
  things actually bought most weeks, a pantry that fills as shopping is
  confirmed rather than in one sitting, and a planner that degrades
  honestly when it knows almost nothing - fewer claims, not worse
  suggestions dressed up. Cost: a day, most of it deciding what the
  smallest useful seed is. Risk: a seed shipped as data rather than as the
  user's own, which puts made-up prices into a budget.

- **Neither cadence is scheduled.** Two kinds of event, one format. Each
  recipe publishes a ready time, so the plan groups its cooking into at
  most two sessions a week where it can, each session's event carrying the
  summed time of what is cooked in it. The grocery list groups the same
  way into at most two shopping trips, split by store, since Whole Foods
  and Costco are not the same errand. Both come out as `.ics`, and nothing
  consumes them yet - that is a later tool - so they are written to disk
  and served, not sent anywhere. A session has a length cap as well as a
  count: capping the count alone optimises straight towards one four-hour
  Sunday, which is the outcome nobody wants and the arithmetic prefers.
  Cost: a day; risk: two trips and two cook sessions constrain each other
  through shelf life, because a Thursday shop cannot feed a Monday cook.

- **Nothing runs unattended.** A clock of its own, as a service beside the
  board rather than a thread inside it or a cron daemon under it, waking
  to see what is due and sleeping again. Times come from the environment,
  `AIOLI_PLAN_AT` and `TZ`, the way the refresher next door takes them.

  The ledger is the part that earns the item. Every job writes a row keyed
  by the period it covers and not the moment it ran - `plan_week` for
  `2026-W39`, started, finished, outcome - and refuses a second run for a
  period already done unless forced. That one rule is what makes a retry
  safe, stops a laptop waking on Monday from planning the week twice, and
  stops one meal decrementing the pantry twice. It is also what the mails
  read to say what happened.

  Two behaviours follow from it. On start, a period that is due and has no
  row is run, so a machine asleep on Saturday morning catches up on
  Saturday afternoon instead of skipping the week in silence. And a run
  checks the quota it needs before it begins, then defers or plans fewer
  days, because half a planned week is worse than an honest postponement.
  A failed run still reports, saying what broke and naming the last good
  plan. Cost: half a day.

- **Nothing tells you any of this.** Two mails a week, and they are not
  the same mail twice.

  Saturday, after the planning run: the week's plan, the list by store,
  the total against the budget, and the trips and cook sessions as things
  to do. Both `.ics` files ride along as attachments, which is how the
  calendar gets filled today without waiting for the tool that will read
  them properly.

  Midweek: what is left, what turns soon, and the confirmations the pantry
  needs to stay true. That is the real job; the summary is how it earns
  being opened. Each confirmation is a link into the board, which reaches
  a phone over the tailnet, so answering is a tap at the moment the answer
  is known rather than a chore deferred to the next time someone sits at
  the machine.

  A failed run mails too, on the same schedule, saying what broke and what
  the last good plan was. SMTP credentials in `.env` beside the API key.
  Cost: a day; risk: a mail nobody reads is a pantry nobody corrects, so
  brevity is a requirement and not a preference.

- **The household's facts are the chef's columns.** Household size, the
  budget per meal, the evenings that are free and what the household will
  not eat are facts the chef reads and does not own, lodged with it only
  because it exists first. They belong in one table of settings, each with
  a source, so that the day a figure starts arriving from another agent is
  a change of source and not a migration. Doing it now is a table; doing
  it after the accountant is a migration and a reconciliation. Cost: half
  a day.

- **Nothing outside can ask AIoli anything.** The functions the chef
  already has internally - the week's plan, what is in the pantry, the
  grocery list, the cooking sessions - published as MCP tools, read-only
  to start. This is the whole integration story for the fleet, and it is
  nearly free precisely because the functions exist anyway: an accountant
  reconciling a grocery spend should not need to know what a recipe is.
  Worth doing once the planner and the list are real, and not before,
  since a tool over a function that does not work yet is a lie with a
  schema. Cost: half a day.

- **The container holds three secrets and no policy.** A Spoonacular key,
  SMTP credentials that can send mail as the household, and eventually a
  signed-in Amazon session that can reach a cart. The fleet's rule says no
  agent holds a credential capable of finishing an irreversible act, and
  the Amazon session is the one that tests it: it is allowed to fill a
  cart and must not be able to place the order. A `SECURITY.md` saying
  what is held, what each one can do, what it cannot, and what an attacker
  who reached the container would get. The confirmation links are part of
  this: the tailnet is the perimeter, the board has no login of its own,
  and a link that moves stock should not be guessable. Cost: half a day.

- **The hand-entered data has no copy.** The price book and the pantry are
  hours of a person's typing and exist nowhere else; a dropped volume
  takes both, and with them every price the budget is computed from. A
  dump to a file the user keeps, on a schedule and on demand, restorable
  into an empty database. Unlike a recipe, this is the user's own record,
  so nothing forbids keeping it. Cost: half a day.

- **The kitchen cannot ask out loud.** "What am I cooking tonight" and
  "add milk to the list" are questions asked with both hands busy, which
  is the one moment a screen is the wrong answer. A HomePod cannot run
  code, and Siri intents want an iOS app, so the path is a Shortcut: it
  calls AIoli over the tailnet and speaks the reply, and "Hey Siri, run
  dinner" reaches it from the HomePod. That makes it a few endpoints
  worded for speech rather than an integration, which is why it is cheap
  and why it wants the HTTP surface to be clean first. Cost: half a day,
  once there is something worth asking. Risk: a Shortcut is a thing a
  person maintains by hand on a phone, and it breaks quietly.

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
