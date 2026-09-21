-- The household's own record: what it has decided, what it owns, what it did.
--
-- Nothing Spoonacular authored appears here. A recipe reaches a table only
-- as an id on a live plan, added in a later migration and purged when the
-- plan's period closes (docs/db.md).

-- What the household has decided. One row per fact, each carrying where it
-- came from, so the day a figure starts arriving from another agent is a
-- change of source and not a migration.
create table settings (
    key         text primary key,
    value       text not null,
    source      text not null default 'user'
                check (source in ('user', 'default', 'agent')),
    updated_at  timestamptz not null default now()
);

-- What the household will not eat. Kept apart from settings because there
-- are many of them and they are queried as a set.
create table dietary_rule (
    id      integer primary key generated always as identity,
    kind    text not null check (kind in ('diet', 'intolerance', 'dislike')),
    value   text not null,
    note    text,
    unique (kind, value)
);

-- What is in the kitchen. A recipe wanting a pan that is not here is
-- fiction that reads as a good suggestion.
create table equipment (
    name    text primary key,
    present boolean not null default true
);

-- What is in the house, in two grades. A perishable carries a quantity, a
-- unit and a shelf life, because that is where waste happens and where the
-- arithmetic has to work. A staple is in stock or running low: nobody
-- weighs their rice.
create table pantry (
    id          integer primary key generated always as identity,
    ingredient  text not null,
    grade       text not null check (grade in ('perishable', 'staple')),
    -- perishables
    quantity    numeric,
    unit        text,
    acquired_on date,
    shelf_life_days integer,
    -- staples
    level       text check (level in ('in_stock', 'low', 'out')),
    updated_at  timestamptz not null default now(),
    constraint perishable_is_measured check (
        grade <> 'perishable' or (quantity is not null and unit is not null)),
    constraint staple_has_a_level check (
        grade <> 'staple' or level is not null)
);

create index pantry_by_ingredient on pantry (lower(ingredient));

-- Every change to the pantry, and what caused it. This is how the pantry
-- tells the truth: three weeks of unrecorded cooking and the table above
-- describes a kitchen that does not exist.
create table stock_move (
    id          integer primary key generated always as identity,
    pantry_id   integer references pantry (id) on delete set null,
    ingredient  text not null,
    quantity    numeric,
    unit        text,
    reason      text not null check (reason in
                ('bought', 'cooked', 'finished', 'discarded', 'corrected')),
    happened_at timestamptz not null default now(),
    note        text
);

create index stock_move_by_time on stock_move (happened_at desc);

-- What was actually eaten, by ingredient and method. This is what variety
-- reads: not "do not repeat recipe 4821" but "there has been chicken thigh
-- three times this month", which is the household's own history and keeps
-- indefinitely.
create table eating_history (
    id          integer primary key generated always as identity,
    eaten_on    date not null,
    slot        text not null check (slot in ('lunch', 'dinner')),
    ingredient  text,
    method      text,
    created_at  timestamptz not null default now()
);

create index eating_history_by_date on eating_history (eaten_on desc);

-- The scheduler's ledger: a job keyed by the period it covers, not the
-- moment it ran, so a second run for a done period is refused and a laptop
-- waking on Monday does not plan the week twice.
create table run (
    id          integer primary key generated always as identity,
    job         text not null,
    period      text not null,
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    outcome     text check (outcome in ('ok', 'failed', 'deferred')),
    detail      text,
    unique (job, period)
);

-- Points spent per day, so a run can know before it starts whether it can
-- finish rather than half-planning a week.
--
-- The one table in this file the kitchen does not own. It is written by the
-- thing that spends the points and read by the thing that decides whether to
-- start, both of which are recipes/client.py; a ledger of what we spent at
-- somebody else's service is not the household's record of what it has.
create table api_usage (
    day     date primary key,
    points  integer not null default 0,
    calls   integer not null default 0
);
