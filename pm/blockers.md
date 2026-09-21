# What only you can provide

The MVP is built. Every item under Done in the backlog landed, the suite is
401 tests against a real PostgreSQL, and the stack comes up under compose
with every page answering. None of that says anything true yet, because
everything below is fact about your household that cannot be invented.

Ordered by what unblocks the most.

## Before the planner can say anything real

- **A Spoonacular key.** Sign up at <https://spoonacular.com/food-api/console>
  and put it in `.env` as `SPOONACULAR_KEY`. The free tier is 50 points a
  day, which will not plan a week; Cook is $29 a month for 1,500. Start
  free - it is enough to prove the integration - and upgrade when the
  planner earns it. Until it lands, the client has never spoken to the real
  service: it is exercised against hand-written fixtures, and the one test
  that would call the live API skips itself without a key.

  Set `SPOONACULAR_TIER` beside it, `free` or `cook`, so a run knows what
  it can afford before it starts.

- **What you will not eat.** Three lists, any of which may be empty: a diet
  if you keep one, allergies and intolerances, and plain dislikes. The
  dislikes matter most - they are what stops a technically valid suggestion
  you would never cook. They go in on the settings page.

- **What is in your kitchen.** Only the equipment a recipe might assume and
  you might lack: food processor, blender, stand mixer, Dutch oven, slow
  cooker, pressure cooker, air fryer, rice cooker, cast iron. A dish that
  wants a pan you do not have is dropped rather than suggested.

## Before a plan means anything

- **Your pantry, once.** The first load is the only tedious one. A
  perishable wants a quantity, a unit and roughly when it arrived; a staple
  wants only whether you have it. Twenty or thirty lines is plenty - the
  shopping and cooking confirmations keep it current after that, which is
  the whole point of the ledger.

- **Your week's shape.** Which days you shop and which evenings you cook.
  The defaults are two of each; the days are guesses until you say.

- **How long you will cook.** A weeknight ceiling and a weekend one. The
  defaults are 45 minutes and 90.

- **Household size.** Assumed to be one. Every serving count follows from
  it, so say if that is wrong.

## Later, and only when the feature that needs it is built

- **Tailscale on the host**, so the midweek mail's confirmation links reach
  your phone. `tailscale serve` points the tailnet at the board without
  changing what the container binds to. Needed when the mails exist.

- **SMTP credentials** for those two mails.

- **A decision on prices**, after the MVP has run a month. The price book is
  yours to keep, and seeding it is the same kind of typing as the pantry.

## Two decisions, not data

- **Where the shared stove lives.** The board holds one hour-long hold over
  the recipe service and the grocery list holds another, so a dish read on
  the list and confirmed within the hour costs two points instead of one.
  Merging them needs an owner named, which is a judgement about the shape
  of the thing rather than a cleanup.

- **What promotes a draft to live.** A planned week is saved as a draft and
  nothing sets it live, so the one-live-plan-per-period constraint has
  never fired. Deciding what promotes one - opening the week, the first
  confirmation, a button - is a product question.

## Not blocked on you

The container, the schema, the recipe client and its fixtures, the pantry
and its ledger, the ingredient matching and unit conversion, the planner,
the grocery list, the board and the steps at the stove are all built and
tested. The largest remaining gap is ours, not yours: nothing calls the
planner outside the suite, so a deployed instance can only say that no week
is planned. That is the first item under "After the MVP".
