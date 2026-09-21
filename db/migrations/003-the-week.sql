-- The week: what a run decided the household would eat, and what it did.
--
-- This is the one place a recipe id is written down, and it is written as an
-- integer and nothing else. No title, no description, no instructions, no
-- image, no ingredient text: a pointer so the board can re-fetch a meal while
-- the plan is live, purged the moment the period closes (docs/db.md). If a
-- column holding the service's words ever appears beside `recipe_id`, the
-- line has been crossed and the answer is to delete the column, not to argue
-- about it.

-- A period, its state, and the run that produced it.
--
-- The four states are the four honest things a week can be. A 'draft' is
-- planned and not yet the week being eaten; 'live' is the week in force, and
-- the only state the recipe pointers may be read in; 'closed' is a finished
-- week with its pointers purged, which shows what it consumed rather than
-- what it was called. 'unfilled' is the one that earns its place: a week the
-- planner could not fill, because there is no key, the day's points are gone
-- or nothing came back this kitchen can cook. It is kept rather than
-- discarded, since a week that says plainly it could not be planned is worth
-- more to the person reading the board than a missing row.
create table plan (
    id          integer primary key generated always as identity,
    period      text not null,
    starts_on   date not null,
    ends_on     date not null,
    state       text not null default 'draft'
                check (state in ('draft', 'live', 'closed', 'unfilled')),
    run_id      integer references run (id) on delete set null,
    note        text,
    created_at  timestamptz not null default now(),
    closed_at   timestamptz,
    constraint a_period_runs_forwards check (ends_on >= starts_on),
    constraint closed_says_when check ((state = 'closed') = (closed_at is not null))
);

-- One live plan to a period. `run` already refuses a second run for a period
-- it has done; this is the same rule where it actually bites, because two
-- live plans for one week are two menus and nothing could say which of them
-- the pantry was moved for. A superseded draft may sit beside the live one.
create unique index plan_one_live_period on plan (period) where state = 'live';

create index plan_by_period on plan (period, created_at desc);

-- A date, a slot, servings, the pairing, whether it was skipped or cooked,
-- and the live recipe pointer.
--
-- `kind` is the settled decision in a column: a slot is filled either by a
-- cook or by a portion of an earlier cook, and `pairs_with` names which cook
-- (pm/backlog.md). A null kind is a slot nothing fills - the search found
-- nothing for that evening, or what it would have eaten was skipped - and it
-- is still a row, so the board shows an empty Tuesday rather than no Tuesday.
--
-- `servings` is what this sitting puts on the table, which is the household
-- size. The batch is therefore the cook's servings plus those of the portion
-- that follows it, and that sum is the whole of "cooked once, eaten twice".
--
-- `cooked_at` is only the plan's own note that the meal happened. The stock
-- it moved is in `stock_move` under the cause 'plan_meal:<id>', which is what
-- makes a confirmation arriving twice harmless (kitchen/moves.py).
create table plan_meal (
    id          integer primary key generated always as identity,
    plan_id     integer not null references plan (id) on delete cascade,
    meal_on     date not null,
    slot        text not null check (slot in ('lunch', 'dinner')),
    servings    integer not null default 0 check (servings >= 0),
    kind        text check (kind in ('cook', 'leftovers')),
    pairs_with  integer references plan_meal (id) on delete set null,
    skipped     boolean not null default false,
    cooked_at   timestamptz,
    recipe_id   integer,
    note        text,
    unique (plan_id, meal_on, slot),
    constraint a_meal_does_not_eat_itself check (pairs_with is distinct from id),
    constraint leftovers_come_from_a_cook check (
        kind <> 'leftovers' or pairs_with is not null),
    -- The pointer sits on the cook and nowhere else, because the cook is the
    -- dish that was looked up. A portion of it follows `pairs_with` to the
    -- same id rather than keeping a second copy, which is one fewer place a
    -- purge has to reach. `is not distinct from` rather than `=` because a
    -- check that comes out null is a check that passed, and a pointer on a
    -- row with no kind at all went straight through the obvious spelling.
    constraint only_a_cook_points_at_a_recipe check (
        recipe_id is null or kind is not distinct from 'cook'),
    -- A skipped meal is left empty, which is the whole of what skipping
    -- means: no dish, no pairing, nobody served.
    constraint a_skipped_meal_is_empty check (
        not skipped or (kind is null and recipe_id is null
                        and pairs_with is null and servings = 0)),
    constraint an_empty_slot_serves_nobody check (
        kind is not null or servings = 0)
);

create index plan_meal_by_date on plan_meal (meal_on, slot);

-- What the purge has to find: the pointers still live. Small by construction
-- - fourteen rows a week - but this is the index the closing run reads, and
-- naming it says out loud that the column is meant to empty.
create index plan_meal_live_pointers on plan_meal (plan_id) where recipe_id is not null;
