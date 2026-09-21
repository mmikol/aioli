# What only you can provide

Everything in the MVP that could be built without you is being built. This
is the short list of what it cannot invent, in the order it becomes
blocking. Nothing here is code; all of it is fact about your household or
an account only you can open.

## Before the planner can run at all

- **A Spoonacular key.** Sign up at <https://spoonacular.com/food-api/console>
  and put it in `.env` as `SPOONACULAR_KEY`. The free tier is 50 points a
  day, which will not plan a week; Cook is $29 a month for 1,500. Start
  free - it is enough to prove the integration - and upgrade when the
  planner is worth it. Until this lands, the client is exercised against
  hand-written fixtures and has never spoken to the real service.

- **What you will not eat.** Three lists, any of which may be empty:
  a diet if you keep one (vegetarian, pescetarian, and so on), allergies
  and intolerances, and plain dislikes. The dislikes matter most - they are
  what stops a technically-valid suggestion you would never cook.

- **What is in your kitchen.** The equipment worth naming is only what a
  recipe might assume and you might lack: food processor, blender, stand
  mixer, Dutch oven, slow cooker, pressure cooker, air fryer, rice cooker,
  cast iron, a second oven shelf. Tell me which you have and I will filter
  on the rest.

## Before a plan means anything

- **Your pantry, once.** The first load is the only tedious one. Perishables
  want a quantity, a unit and roughly when they came in; staples want only
  whether you have them. Twenty or thirty lines is plenty to start - the
  shopping confirmations keep it current after that.

- **Your week's shape.** Which days you shop and which evenings you cook.
  Defaults are two shops and two cook sessions, but the days are guesses
  until you say.

- **How long you will cook.** A weeknight ceiling and a weekend one. The
  defaults are 45 minutes and 90; they are only defaults.

- **Household size.** Assumed to be one. Say if that is wrong, because
  every serving count follows from it.

## Later, not now

- **Tailscale on this machine**, so the midweek mail's confirmation links
  reach your phone. Only needed once notifications exist; `tailscale serve`
  points the tailnet at the board without changing what the container binds
  to.

- **SMTP credentials** for the two mails, once they are built.

- **A decision on prices**, when the MVP has run a month: the price book is
  yours to keep, and seeding it is the same kind of typing as the pantry.

## What is not blocked on you

The container, the schema, the recipe client, the pantry and its ledger,
the ingredient matching, the planner, the grocery list and the board are
all being built now. They are tested against fixtures and a local database,
so none of them waits on the list above - they simply have nothing real to
say until it arrives.
